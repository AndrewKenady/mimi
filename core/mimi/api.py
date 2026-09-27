"""HTTP API for the MIMI app (all JSON under /api, plus a few public routes)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import __version__, log, system, tools
from .app import MAIN_PORT, Services, ctx_or_none, get_ctx, is_local, member_ctx, owner_ctx
from .auth import SESSION_COOKIE, AuthError, Ctx, public_user
from .kiwix import COLLECTION_LABELS, book_dict, hit_dict
from .settings import DEVICE_SECTIONS, USER_SECTIONS, SettingsError

L = log.get("api")
router = APIRouter(prefix="/api")
public_router = APIRouter()


def S(request: Request) -> Services:
    return request.app.state.svc


def _cookie(resp: Response, token: str, request: Request) -> None:
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=request.url.scheme == "https", max_age=60 * 60 * 24 * 180)


# =========================================================================== basics
@router.get("/ping")
async def ping():
    return {"ok": True, "version": __version__}


@router.get("/health")
async def health(request: Request):
    return S(request).health()


@router.get("/bootstrap")
async def bootstrap(request: Request):
    """Everything the UI needs on launch, in one round trip."""
    svc = S(request)
    ctx = ctx_or_none(request)
    local = is_local(request)
    base = {
        "version": __version__,
        "local": local,
        "portable": svc.paths.portable,
        "needs_setup": not svc.auth.has_owner(),
        "locked": bool(local and svc.auth.has_owner() and ctx is None),
        "me": public_user(ctx.user) if ctx else None,
        "modes": svc.chats.modes,
        "collections": COLLECTION_LABELS,
    }
    if not ctx:
        base["guest_access"] = svc.settings.device("sharing").guest_access
        return base
    base.update(
        settings=svc.settings.all_for(ctx.id, ctx.role),
        models=svc.models.status(),
        health=svc.health(),
        location=svc.location.status(),
        hardware={k: svc.hw.get(k) for k in ("device", "cpu", "ram_installed_gb", "backend", "profile", "battery", "gpus")},
        share=svc.share.status(owner=ctx.is_owner),
        features=_features(svc, ctx),
    )
    return base


def _features(svc: Services, ctx: Ctx) -> dict:
    guest_allowed = set(svc.settings.device("sharing").guest_features) if ctx.is_guest else None

    def ok(name: str) -> bool:
        return guest_allowed is None or name in guest_allowed

    return {
        "chat": True,
        "library": ok("library") and svc.kiwix_service.alive(),
        "map": ok("map"),
        "voice": ok("voice") and svc.voice.tts_available() and svc.voice.stt_available("small"),
        "scribe": not ctx.is_guest and svc.voice.stt_available("small"),
        "lens": ok("lens"),
        "memory": not ctx.is_guest,
        "files": not ctx.is_guest,
        "settings": True,
    }


@router.websocket("/events")
async def events_ws(ws: WebSocket):
    svc: Services = ws.app.state.svc
    token = ws.cookies.get(SESSION_COOKIE)
    user = svc.auth.resolve(token) if token else None
    server = ws.scope.get("server") or ("", 0)
    local = server[1] == MAIN_PORT and (ws.client.host if ws.client else "") in ("127.0.0.1", "::1", "testclient")
    if not user and local and svc.settings.device("general").local_auto_login and not svc.settings.device("general").require_pin:
        user = svc.auth.owner()
    await ws.accept()
    sub = svc.events.subscribe(user["id"] if user else None, user["role"] if user else "anon")
    try:
        for ev in list(svc.events.last.values()):
            await ws.send_text(json.dumps(ev))
        while True:
            getter = asyncio.create_task(sub.queue.get())
            recv = asyncio.create_task(ws.receive_text())
            done, pending = await asyncio.wait({getter, recv}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            if getter in done:
                await ws.send_text(json.dumps(getter.result()))
            elif recv in done:
                try:
                    recv.result()
                except Exception:
                    break
            else:
                await ws.send_text('{"type":"ping"}')
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        svc.events.unsubscribe(sub)


# =========================================================================== auth & users
class SetupIn(BaseModel):
    name: str
    pin: str | None = None


class LoginIn(BaseModel):
    name: str
    secret: str


class GuestIn(BaseModel):
    name: str | None = None


class UnlockIn(BaseModel):
    pin: str


class UserIn(BaseModel):
    name: str
    role: str = "user"
    pin: str | None = None
    password: str | None = None


class UserPatch(BaseModel):
    name: str | None = None
    pin: str | None = None
    password: str | None = None
    color: str | None = None


@router.get("/auth/me")
async def me(request: Request):
    ctx = ctx_or_none(request)
    svc = S(request)
    return {"user": public_user(ctx.user) if ctx else None, "needs_setup": not svc.auth.has_owner(), "local": is_local(request)}


@router.post("/auth/setup")
async def setup(body: SetupIn, request: Request):
    svc = S(request)
    if svc.auth.has_owner():
        raise HTTPException(409, "MIMI is already set up.")
    if not is_local(request):
        raise HTTPException(403, "Set up MIMI on the device itself.")
    try:
        u = svc.auth.create(body.name, "owner", pin=body.pin or None)
    except AuthError as e:
        raise HTTPException(400, str(e))
    token = svc.auth.create_session(u["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "")
    resp = JSONResponse({"user": public_user(u)})
    _cookie(resp, token, request)
    return resp


@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    svc = S(request)
    u = svc.auth.by_name(body.name)
    if not u or u["role"] == "guest" or not svc.auth.verify(u, body.secret):
        await asyncio.sleep(0.8)
        raise HTTPException(401, "That name and password/PIN don't match.")
    token = svc.auth.create_session(u["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "")
    resp = JSONResponse({"user": public_user(u)})
    _cookie(resp, token, request)
    return resp


class PairIn(BaseModel):
    name: str


class DecideIn(BaseModel):
    approve: bool


@router.post("/auth/pair")
async def pair_request(body: PairIn, request: Request):
    """A browser on the network asks the device to let it sign in (no PIN needed)."""
    svc = S(request)
    if is_local(request):
        raise HTTPException(400, "You're on the MIMI device already.")
    u = svc.auth.by_name(body.name.strip())
    if not u or u["role"] == "guest":
        await asyncio.sleep(0.5)
        raise HTTPException(404, "There's no account with that name on this MIMI.")
    try:
        return svc.pairing.request(u, request.headers.get("user-agent", ""), request.client.host if request.client else "")
    except ValueError as e:
        raise HTTPException(429, str(e))


@router.get("/auth/pair/pending")
async def pair_pending(request: Request, ctx: Ctx = Depends(owner_ctx)):
    if not is_local(request):
        raise HTTPException(403, "Sign-in requests are approved on the MIMI device.")
    return {"requests": S(request).pairing.pending()}


@router.post("/auth/pair/{rid}/decide")
async def pair_decide(rid: str, body: DecideIn, request: Request, ctx: Ctx = Depends(owner_ctx)):
    # Only the owner, on the device's own screen, can let someone in.
    if not is_local(request):
        raise HTTPException(403, "Sign-in requests are approved on the MIMI device.")
    return {"status": S(request).pairing.decide(rid, body.approve)}


@router.get("/auth/pair/{rid}")
async def pair_poll(rid: str, request: Request, poll: str = ""):
    svc = S(request)
    status, user = svc.pairing.claim(rid, poll)
    if status != "approved" or not user:
        return {"status": status}
    token = svc.auth.create_session(user["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "")
    resp = JSONResponse({"status": "approved", "user": public_user(user)})
    _cookie(resp, token, request)
    return resp


@router.post("/auth/unlock")
async def unlock(body: UnlockIn, request: Request):
    svc = S(request)
    owner = svc.auth.owner()
    if not owner or not svc.auth.verify(owner, body.pin):
        await asyncio.sleep(0.8)
        raise HTTPException(401, "Wrong PIN.")
    token = svc.auth.create_session(owner["id"], "device", "127.0.0.1")
    resp = JSONResponse({"user": public_user(owner)})
    _cookie(resp, token, request)
    return resp


@router.post("/auth/guest")
async def guest(body: GuestIn, request: Request):
    svc = S(request)
    share = svc.settings.device("sharing")
    if not share.guest_access:
        raise HTTPException(403, "Guest access is turned off.")
    active_guests = [s for s in svc.auth.active_remote_sessions(3600) if s["role"] == "guest"]
    if len(active_guests) >= share.max_guests:
        raise HTTPException(429, "MIMI is busy with other guests right now.")
    try:
        u = svc.auth.create((body.name or "Guest").strip()[:30] or "Guest", "guest")
    except AuthError as e:
        raise HTTPException(400, str(e))
    token = svc.auth.create_session(u["id"], request.headers.get("user-agent", ""), request.client.host if request.client else "")
    resp = JSONResponse({"user": public_user(u)})
    _cookie(resp, token, request)
    return resp


@router.post("/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        S(request).auth.end_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/users")
async def users(request: Request, ctx: Ctx = Depends(owner_ctx)):
    return [public_user(u) for u in S(request).auth.list()]


@router.post("/users")
async def create_user(body: UserIn, request: Request, ctx: Ctx = Depends(owner_ctx)):
    if body.role not in ("user",):
        raise HTTPException(400, "New accounts are regular users.")
    if not (body.pin or body.password):
        raise HTTPException(400, "Give the account a PIN or password so it can sign in from a phone.")
    try:
        return public_user(S(request).auth.create(body.name, "user", pin=body.pin, password=body.password))
    except AuthError as e:
        raise HTTPException(400, str(e))


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: UserPatch, request: Request, ctx: Ctx = Depends(get_ctx)):
    if user_id != ctx.id and not ctx.is_owner:
        raise HTTPException(403)
    try:
        return public_user(S(request).auth.update(user_id, name=body.name, pin=body.pin, password=body.password, color=body.color))
    except AuthError as e:
        raise HTTPException(400, str(e))


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    if user_id == ctx.id:
        raise HTTPException(400, "The owner account can't be deleted.")
    svc.docs.purge_user(user_id)
    svc.auth.delete(user_id)
    return {"ok": True}


# =========================================================================== settings
@router.get("/settings")
async def get_settings(request: Request, ctx: Ctx = Depends(get_ctx)):
    return S(request).settings.all_for(ctx.id, ctx.role)


@router.patch("/settings/{scope}/{section}")
async def patch_settings(scope: str, section: str, body: dict[str, Any], request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    if scope == "device" and not ctx.is_owner:
        raise HTTPException(403, "Only the device owner can change device settings.")
    try:
        before = svc.settings.device(section).model_dump() if scope == "device" and section in DEVICE_SECTIONS else None
        new = svc.settings.update(scope, section, body, user_id=ctx.id, role=ctx.role)
    except SettingsError as e:
        raise HTTPException(422, str(e))
    await _apply_side_effects(svc, scope, section, before, new)
    svc.events.publish("settings", {"scope": scope, "section": section, "value": new}, user_id=None if scope == "device" else ctx.id)
    return new


async def _apply_side_effects(svc: Services, scope: str, section: str, before: dict | None, new: dict) -> None:
    if scope != "device" or before is None:
        return
    if section == "general" and before.get("launch_at_startup") != new.get("launch_at_startup"):
        try:
            system.set_autostart(new["launch_at_startup"], svc.paths)
        except Exception as e:
            svc.settings.update("device", "general", {"launch_at_startup": system.autostart_enabled()})
            raise HTTPException(400, f"Couldn't change startup setting: {e}")
    if section == "sharing":
        if new["enabled"] and (not svc.share.running or before.get("https_port") != new["https_port"]):
            await svc.share.stop()
            await svc.share.start(svc.app)
        elif not new["enabled"] and svc.share.running:
            await svc.share.stop()
    if section == "models" and any(before.get(k) != new.get(k) for k in ("profile", "main", "context")):
        async def reload():
            await svc.models.unload()
            await svc.models.preload()
        asyncio.create_task(reload())
    if section == "knowledge" and before.get("extra_zim_dirs") != new.get("extra_zim_dirs"):
        await svc.kiwix_service.restart()
        svc.kiwix.invalidate()
    if section == "knowledge":
        svc.kiwix.invalidate()


@router.post("/settings/{scope}/{section}/reset")
async def reset_settings(scope: str, section: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    if scope == "device" and not ctx.is_owner:
        raise HTTPException(403)
    if (scope == "device" and section not in DEVICE_SECTIONS) or (scope == "user" and section not in USER_SECTIONS):
        raise HTTPException(404)
    value = S(request).settings.reset(scope, section, user_id=ctx.id)
    S(request).events.publish("settings", {"scope": scope, "section": section, "value": value}, user_id=None if scope == "device" else ctx.id)
    return value


@router.get("/settings/export")
async def export_settings(request: Request, ctx: Ctx = Depends(get_ctx)):
    data = S(request).settings.export(ctx.id, ctx.role)
    if not ctx.is_owner:
        data.pop("device", None)
    else:
        data["device"]["sharing"].pop("wifi_password", None)
    return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="mimi-settings.json"'})


@router.post("/settings/import")
async def import_settings(body: dict[str, Any], request: Request, ctx: Ctx = Depends(get_ctx)):
    try:
        S(request).settings.import_(body, ctx.id, ctx.role, include_device=ctx.is_owner)
    except SettingsError as e:
        raise HTTPException(422, str(e))
    return S(request).settings.all_for(ctx.id, ctx.role)


# =========================================================================== models
@router.get("/models")
async def models(request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    return {"status": svc.models.status(), "catalog": [m.public() for m in svc.catalog.models.values()],
            "profiles": svc.catalog.profiles, "hardware_profile": svc.hw.get("profile")}


class LoadIn(BaseModel):
    role: str | None = "main"
    model: str | None = None


@router.post("/models/load")
async def load_model(body: LoadIn, request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    spec = svc.catalog.get(body.model) if body.model else svc.models.model_for(body.role or "main")
    if not spec or not spec.installed:
        raise HTTPException(404, "That model isn't installed.")
    asyncio.create_task(svc.models.ensure(spec))
    return {"ok": True, "model": spec.id}


@router.post("/models/unload")
async def unload_model(request: Request, ctx: Ctx = Depends(owner_ctx)):
    await S(request).models.unload()
    return {"ok": True}


# =========================================================================== tools
@router.get("/tools")
async def list_tools(request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    return {"tools": tools.catalog(svc), "folder": str(svc.paths.root / "tools")}


@router.post("/tools/reload")
async def reload_tools(request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    await asyncio.to_thread(tools.load_plugins, svc.paths.root / "tools")
    return {"tools": tools.catalog(svc), "folder": str(svc.paths.root / "tools")}


# =========================================================================== chats
class ChatIn(BaseModel):
    title: str | None = None
    mode: str | None = None
    temporary: bool = False
    project: str | None = None


class ChatPatch(BaseModel):
    title: str | None = None
    project: str | None = None
    mode: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


class MessageIn(BaseModel):
    content: str = ""
    attachments: list[str] = []
    mode: str | None = None
    role: str | None = None
    voice: bool = False
    regenerate: str | None = None
    edit: str | None = None
    temporary: bool = False
    think: bool | None = None


class HeadIn(BaseModel):
    message_id: str


@router.get("/chats")
async def list_chats(request: Request, q: str | None = None, archived: bool = False, project: str | None = None, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    return {"chats": svc.chats.list(ctx, q=q, archived=archived, project=project), "projects": svc.chats.projects(ctx)}


@router.post("/chats")
async def create_chat(body: ChatIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    return S(request).chats.create(ctx, title=body.title, mode=body.mode, temporary=body.temporary, project=body.project)


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    chat = S(request).chats.get_full(ctx, chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


@router.patch("/chats/{chat_id}")
async def patch_chat(chat_id: str, body: ChatPatch, request: Request, ctx: Ctx = Depends(get_ctx)):
    chat = S(request).chats.update(ctx, chat_id, **body.model_dump())
    if not chat:
        raise HTTPException(404)
    return chat


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    return {"ok": S(request).chats.delete(ctx, chat_id)}


@router.delete("/chats")
async def delete_all_chats(request: Request, ctx: Ctx = Depends(get_ctx)):
    return {"deleted": S(request).chats.delete_all(ctx)}


@router.post("/chats/{chat_id}/head")
async def set_head(chat_id: str, body: HeadIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    chat = S(request).chats.switch_head(ctx, chat_id, body.message_id)
    if not chat:
        raise HTTPException(404)
    return chat


@router.post("/chats/{chat_id}/stop")
async def stop_chat(chat_id: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    return {"stopped": S(request).chats.stop(chat_id)}


def _sse(stream_factory) -> StreamingResponse:
    """Run the turn in its own task so it completes (and is saved) even if the client disconnects."""
    queue: asyncio.Queue = asyncio.Queue()

    async def pump():
        try:
            async for ev in stream_factory():
                await queue.put(ev)
        except Exception as e:
            L.exception("stream failed")
            await queue.put({"event": "error", "data": {"message": str(e)}})
        finally:
            await queue.put(None)

    task = asyncio.create_task(pump())

    async def gen():
        yield ": mimi\n\n"
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if ev is None:
                break
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
        await task

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chats/{chat_id}/messages")
async def send_message(chat_id: str, body: MessageIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    return _sse(lambda: svc.chats.send(ctx, chat_id if chat_id != "new" else None, **body.model_dump()))


@router.get("/chats/{chat_id}/export")
async def export_chat(chat_id: str, request: Request, format: str = "md", ctx: Ctx = Depends(get_ctx)):
    chat = S(request).chats.get_full(ctx, chat_id)
    if not chat:
        raise HTTPException(404)
    if format == "json":
        return JSONResponse(chat, headers={"Content-Disposition": f'attachment; filename="chat-{chat_id}.json"'})
    lines = [f"# {chat.get('title') or 'Chat'}", ""]
    for m in chat["messages"]:
        who = ctx.user["name"] if m["role"] == "user" else "MIMI"
        lines += [f"**{who}:**", "", m["content"], ""]
        for s in (m["meta"] or {}).get("sources") or []:
            lines.append(f"> [{s['n']}] {s['title']} — {s.get('book_title') or s.get('type')}")
        lines.append("")
    safe = re.sub(r"[^\w\- ]+", "", chat.get("title") or "chat")[:60] or "chat"
    return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": f'attachment; filename="{safe}.md"'}, media_type="text/markdown")


# =========================================================================== memory
class MemoryIn(BaseModel):
    text: str
    category: str = "other"
    pinned: bool = False


class MemoryPatch(BaseModel):
    text: str | None = None
    category: str | None = None
    pinned: bool | None = None
    status: str | None = None


@router.get("/memories")
async def list_memories(request: Request, status: str | None = None, q: str | None = None, ctx: Ctx = Depends(member_ctx)):
    svc = S(request)
    return {"memories": svc.memory.list(ctx.id, status=status, q=q), "mode": svc.memory.mode(ctx),
            "paused": svc.settings.user(ctx.id, "privacy", ctx.role).memory_paused}


@router.post("/memories")
async def add_memory(body: MemoryIn, request: Request, ctx: Ctx = Depends(member_ctx)):
    try:
        return await S(request).memory.add(ctx.id, body.text, body.category, "active", pinned=body.pinned)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/memories/{mem_id}")
async def patch_memory(mem_id: str, body: MemoryPatch, request: Request, ctx: Ctx = Depends(member_ctx)):
    m = await S(request).memory.update(ctx.id, mem_id, **body.model_dump())
    if not m:
        raise HTTPException(404)
    return m


@router.post("/memories/{mem_id}/accept")
async def accept_memory(mem_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    m = await S(request).memory.update(ctx.id, mem_id, status="active")
    if not m:
        raise HTTPException(404)
    return m


@router.delete("/memories/{mem_id}")
async def delete_memory(mem_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    return {"ok": S(request).memory.delete(ctx.id, mem_id)}


@router.delete("/memories")
async def clear_memories(request: Request, ctx: Ctx = Depends(member_ctx)):
    return {"deleted": S(request).memory.clear(ctx.id)}


@router.get("/memories/export")
async def export_memories(request: Request, format: str = "json", ctx: Ctx = Depends(member_ctx)):
    mems = S(request).memory.export(ctx.id)
    if format == "md":
        text = "# What MIMI remembers\n\n" + "\n".join(f"- {m['text']} _({m['category']})_" for m in mems if m["status"] == "active")
        return PlainTextResponse(text, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="mimi-memories.md"'})
    return JSONResponse(mems, headers={"Content-Disposition": 'attachment; filename="mimi-memories.json"'})


# =========================================================================== uploads
@router.post("/uploads")
async def upload(request: Request, file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)):
    data = await file.read()
    try:
        return await asyncio.to_thread(S(request).uploads.save, ctx, file.filename or "upload", data, file.content_type)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/uploads/{upload_id}")
async def get_upload(upload_id: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    meta = S(request).uploads.get(ctx, upload_id)
    if not meta:
        raise HTTPException(404)
    return FileResponse(meta["path"], filename=meta["name"], headers={"Cache-Control": "private, max-age=86400"})


# =========================================================================== library (offline reference)
def _library_ok(svc: Services, ctx: Ctx) -> None:
    if ctx.is_guest and "library" not in svc.settings.device("sharing").guest_features:
        raise HTTPException(403, "The library isn't shared with guests.")


@router.get("/library/books")
async def books(request: Request, all: bool = False, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    _library_ok(svc, ctx)
    bs = await svc.kiwix.books(include_disabled=all and ctx.is_owner)
    disabled = set(svc.settings.device("knowledge").disabled_books)
    out = []
    for b in bs:
        d = book_dict(b)
        d["enabled"] = b.name not in disabled and b.alias not in disabled
        out.append(d)
    return {"books": out, "running": svc.kiwix_service.alive(), "collections": COLLECTION_LABELS}


@router.get("/library/search")
async def library_search(request: Request, q: str, collection: str | None = None, book: str | None = None, limit: int = 12, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    _library_ok(svc, ctx)
    b = await svc.kiwix.book(book) if book else None
    hits = await svc.kiwix.search(q, collections=[collection] if collection else None, books=[b.name] if b else None, limit=min(limit, 25))
    return {"results": [hit_dict(h) for h in hits]}


@router.get("/library/suggest")
async def library_suggest(request: Request, q: str, book: str, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    b = await svc.kiwix.book(book)
    if not b:
        return {"results": []}
    return {"results": await svc.kiwix.suggest(q, b.name, 8)}


@router.get("/library/article/{book}/{path:path}")
async def library_article(book: str, path: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    _library_ok(svc, ctx)
    art = await svc.kiwix.reader(book, path)
    if not art:
        raise HTTPException(404, "Article not found in the offline library.")
    return art


@router.get("/library/home/{book}")
async def library_home(book: str, request: Request, ctx: Ctx = Depends(get_ctx)):
    """Resolve a book's main page (kiwix redirects /content/<book> to it)."""
    svc = S(request)
    b = await svc.kiwix.book(book)
    if not b:
        raise HTTPException(404)
    r = await svc.kiwix.http.get(f"{svc.kiwix_service.base}/content/{b.name}", follow_redirects=False)
    loc = r.headers.get("location", "")
    path = loc.split(f"/content/{b.name}/", 1)[-1] if loc else ""
    return {"book": b.alias, "path": path}


# Discover is a friendly Home card, not a search result: skip topics nobody wants
# served to them at random (crimes, disasters, drugs, sexual content).
_DISCOVER_SKIP = re.compile(
    r"murder|killing|shooting|massacre|bombing|terror|genocide|death of|disappearance|suicide|lynching|execution|"
    r"assassination|rape|abuse|kidnapping|crash|disaster|riot|drug|psychedelic|phenethylamine|amphetamine|opioid|"
    r"cannabinoid|overdose|sexual|pornograph|erotic|fetish|nazi|hate group|serial killer",
    re.I,
)
_DISCOVER_JUNK = re.compile(r"(^List_of|discography|filmography|_\(disambiguation\)|^\d{4}_in_|_season$)")
_discover_recent: list[str] = []


async def _discover_item(svc, b, path: str, min_html: int) -> dict | None:
    if not path or _DISCOVER_JUNK.search(path) or _DISCOVER_SKIP.search(path.replace("_", " ")) or path in _discover_recent:
        return None
    art = await svc.kiwix.reader(b.name, path)
    if not art or len(art.get("html", "")) < min_html or _DISCOVER_SKIP.search(art.get("title") or ""):
        return None
    from selectolax.parser import HTMLParser

    paras = [re.sub(r"\s+", " ", p.text()).strip() for p in HTMLParser(art["html"]).css("p")]
    text = re.sub(r"\[\d+\]", "", re.sub(r"\s+", " ", " ".join(p for p in paras if len(p) > 60))).strip()
    if not text or _DISCOVER_SKIP.search(text[:400]):
        return None
    return {"book": b.alias, "book_title": b.title, "path": art["path"], "title": art["title"], "image": art["image"], "excerpt": text[:300]}


@router.get("/library/random")
async def library_random(request: Request, book: str | None = None, near: bool = True, ctx: Ctx = Depends(get_ctx)):
    """A Discover pick: a notable place near the device when the location is known,
    otherwise a substantial random article. Recent picks aren't repeated."""
    svc = S(request)
    bs = await svc.kiwix.books()
    b = await svc.kiwix.book(book) if book else next((x for x in bs if x.collection == "encyclopedia"), bs[0] if bs else None)
    if not b:
        raise HTTPException(404)

    def remember(item: dict) -> dict:
        _discover_recent.append(item["path"])
        del _discover_recent[:-30]
        return item

    cur = svc.location.current() if near and not book else None
    if cur:
        places = await asyncio.to_thread(svc.location.nearby, cur["lat"], cur["lon"], 40, None, 60)
        cands = [p for p in places if p.get("wiki_path")][:25]
        import random

        random.shuffle(cands)
        metric = svc.settings.device("general").units == "metric"
        for p in cands[:8]:
            item = await _discover_item(svc, b, p["wiki_path"], 3000)
            if item and item["image"]:
                d = p.get("distance_km") or 0
                item["reason"] = f"Near you · {d:.1f} km" if metric else f"Near you · {d * 0.621371:.1f} mi"
                return remember(item)
    fallback = None
    for _ in range(12):  # a substantial article (a proxy for notability) with a picture
        r = await svc.kiwix.http.get(f"{svc.kiwix_service.base}/random", params={"content": b.name}, follow_redirects=False)
        loc = r.headers.get("location", "")
        item = await _discover_item(svc, b, loc.split(f"/content/{b.name}/", 1)[-1] if loc else "", 12000)
        if item and item["image"]:
            return remember(item)
        fallback = fallback or item
    if fallback:
        return remember(fallback)
    raise HTTPException(404)


@public_router.get("/kiwix/{path:path}", include_in_schema=False)
async def kiwix_proxy(path: str, request: Request):
    """Media and assets from the offline library (images in articles and citations)."""
    svc = S(request)
    if ctx_or_none(request) is None:
        raise HTTPException(401)
    # Forward the path exactly as the browser encoded it: some ZIM asset names
    # contain literal "%2C", which must reach kiwix-serve still escaped.
    raw = request.scope.get("raw_path") or b""
    raw_path = raw.decode("latin-1")[len("/kiwix/"):] if raw.startswith(b"/kiwix/") else path
    url = f"{svc.kiwix_service.base}/{raw_path}"
    if request.url.query:
        url += "?" + request.url.query
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("range",)}
    client: httpx.AsyncClient = svc.kiwix.http
    req = client.build_request("GET", url, headers=headers)
    upstream = await client.send(req, stream=True, follow_redirects=True)
    passthrough = {k: v for k, v in upstream.headers.items() if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges", "etag", "last-modified")}
    passthrough["Cache-Control"] = "private, max-age=604800"

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(body(), status_code=upstream.status_code, headers=passthrough)


# =========================================================================== my files
@router.get("/files")
async def list_files(request: Request, ctx: Ctx = Depends(member_ctx)):
    return {"files": S(request).docs.list(ctx.id)}


@router.post("/files")
async def add_file(request: Request, file: UploadFile = File(...), ctx: Ctx = Depends(member_ctx)):
    try:
        return await S(request).docs.add_upload(ctx.id, file.filename or "file", await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/files/{doc_id}")
async def delete_file(doc_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    return {"ok": S(request).docs.delete(ctx.id, doc_id)}


@router.get("/files/search")
async def search_files(request: Request, q: str, ctx: Ctx = Depends(member_ctx)):
    return {"results": await S(request).docs.search(ctx.id, q, k=8)}


# =========================================================================== location & maps
class LocationIn(BaseModel):
    lat: float
    lon: float
    label: str | None = None
    accuracy: float | None = None
    manual: bool = False


@router.get("/location")
async def get_location(request: Request, ctx: Ctx = Depends(get_ctx)):
    return S(request).location.status()


@router.post("/location")
async def set_location(body: LocationIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(422, "Invalid coordinates")
    if body.manual:
        if not ctx.is_owner:
            raise HTTPException(403, "Only the owner can set the device location.")
        svc.settings.update("device", "location", {"manual": {"lat": body.lat, "lon": body.lon, "label": body.label}})
    else:
        svc.location.set_client_fix(body.lat, body.lon, body.accuracy)
    status = svc.location.status()
    svc.events.publish("location", status, sticky=True)
    return status


@router.delete("/location/manual")
async def clear_manual_location(request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    svc.settings.update("device", "location", {"manual": None})
    status = svc.location.status()
    svc.events.publish("location", status, sticky=True)
    return status


@router.delete("/location/live")
async def stop_live_location(request: Request, ctx: Ctx = Depends(get_ctx)):
    """A browser stopped streaming its position: forget its last fix now, not in 10 minutes."""
    svc = S(request)
    svc.location.client_fix = None
    status = svc.location.status()
    svc.events.publish("location", status, sticky=True)
    return status


@router.get("/location/nearby")
async def nearby(request: Request, lat: float | None = None, lon: float | None = None, radius: float = 15, kind: str = "all",
                 limit: int = 24, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    if lat is None or lon is None:
        cur = svc.location.current()
        if not cur:
            return {"places": [], "location": None}
        lat, lon = cur["lat"], cur["lon"]
    places = await asyncio.to_thread(svc.location.nearby, lat, lon, min(radius, 100), None if kind == "all" else [kind], min(limit, 60))
    return {"places": places, "location": {"lat": lat, "lon": lon}}


@router.get("/location/search")
async def search_places(request: Request, q: str, ctx: Ctx = Depends(get_ctx)):
    return {"results": await asyncio.to_thread(S(request).location.search, q, 10)}


@router.get("/maps/info")
async def maps_info(request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    tiles = svc.paths.maps / "tiles.pmtiles"
    meta_file = svc.paths.maps / "tiles.json"
    meta = json.loads(meta_file.read_text("utf-8")) if meta_file.exists() else {}
    return {
        "tiles": tiles.exists(),
        "tiles_url": "/maps/tiles.pmtiles" if tiles.exists() else None,
        "size": tiles.stat().st_size if tiles.exists() else 0,
        "assets": (svc.paths.maps / "assets").exists(),
        "bounds": meta.get("bounds"),
        "maxzoom": meta.get("maxzoom"),
        "attribution": "© OpenStreetMap contributors · Protomaps · GeoNames",
    }


class RouteIn(BaseModel):
    to: dict
    origin: dict | None = None  # {lat, lon}; defaults to the current location
    mode: str = "auto"


@router.get("/route/status")
async def route_status(request: Request, ctx: Ctx = Depends(get_ctx)):
    return S(request).routing.status()


@router.post("/route")
async def route(body: RouteIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    if not svc.routing.available():
        raise HTTPException(503, "Offline directions aren't installed yet.")
    origin = body.origin or svc.location.current()
    if not origin:
        raise HTTPException(400, "Set your location first (tap the map), or connect a GPS.")
    units = "kilometers" if svc.settings.device("general").units == "metric" else "miles"
    try:
        return await asyncio.to_thread(svc.routing.route, (float(origin["lat"]), float(origin["lon"])),
                                       (float(body.to["lat"]), float(body.to["lon"])), body.mode, units)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _range_file(path: Path, request: Request, media_type: str) -> Response:
    size = path.stat().st_size
    rng = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=86400"}
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m:
            start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2) or 0))
            end = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
            end = min(end, size - 1)
            if start > end:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
            headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(len(data))})
            return Response(data, status_code=206, headers=headers, media_type=media_type)
    return FileResponse(path, headers=headers, media_type=media_type)


@public_router.get("/maps/{path:path}", include_in_schema=False)
async def maps_static(path: str, request: Request):
    svc = S(request)
    if ctx_or_none(request) is None:
        raise HTTPException(401)
    f = (svc.paths.maps / path).resolve()
    if not str(f).startswith(str(svc.paths.maps.resolve())) or not f.is_file() or f.suffix in (".sqlite", ".db"):
        raise HTTPException(404)
    mt = {".pmtiles": "application/octet-stream", ".pbf": "application/x-protobuf", ".json": "application/json", ".png": "image/png"}.get(f.suffix, None)
    return _range_file(f, request, mt or "application/octet-stream")


# =========================================================================== voice
class TTSIn(BaseModel):
    text: str
    voice: str | None = None
    speed: float | None = None


@router.post("/voice/stt")
async def stt(request: Request, file: UploadFile = File(...), language: str | None = Form(None), ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    data = await file.read()
    if len(data) < 400:
        return {"text": "", "duration": 0}
    model = svc.settings.user(ctx.id, "voice", ctx.role).stt_model if not ctx.is_guest else "small"
    try:
        r = await asyncio.to_thread(svc.voice.transcribe, data, model if model == "small" else "small", language)
    except Exception as e:
        L.exception("stt failed")
        raise HTTPException(500, f"Couldn't transcribe: {e}")
    return {"text": r["text"], "language": r["language"], "duration": r["duration"]}


@router.post("/voice/tts")
async def tts(body: TTSIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    if not svc.voice.tts_available():
        raise HTTPException(503, "The voice model isn't installed.")
    v = svc.settings.user(ctx.id, "voice", ctx.role)
    wav = await asyncio.to_thread(svc.voice.synthesize, body.text, body.voice or v.voice, body.speed or v.speed)
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/voice/warm")
async def voice_warm(request: Request, ctx: Ctx = Depends(get_ctx)):
    """Voice mode opened: load Whisper and Kokoro in the background."""
    svc = S(request)
    asyncio.get_running_loop().run_in_executor(None, svc.voice.warm)
    return {"ok": True}


@router.get("/voice/voices")
async def voices(request: Request, ctx: Ctx = Depends(get_ctx)):
    svc = S(request)
    return {"voices": await asyncio.to_thread(svc.voice.voices), "status": svc.voice.status()}


# =========================================================================== scribe
@router.get("/scribe")
async def scribe_list(request: Request, ctx: Ctx = Depends(member_ctx)):
    return {"notes": S(request).scribe.list(ctx)}


@router.post("/scribe")
async def scribe_create(request: Request, file: UploadFile = File(...), title: str | None = Form(None), ctx: Ctx = Depends(member_ctx)):
    data = await file.read()
    if len(data) < 1000:
        raise HTTPException(400, "That recording is empty.")
    return await S(request).scribe.create(ctx, file.filename or "recording.webm", data, title)


@router.get("/scribe/{note_id}")
async def scribe_get(note_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    n = S(request).scribe.get(ctx, note_id)
    if not n:
        raise HTTPException(404)
    return n


class NotePatch(BaseModel):
    title: str


@router.patch("/scribe/{note_id}")
async def scribe_patch(note_id: str, body: NotePatch, request: Request, ctx: Ctx = Depends(member_ctx)):
    n = S(request).scribe.rename(ctx, note_id, body.title)
    if not n:
        raise HTTPException(404)
    return n


@router.delete("/scribe/{note_id}")
async def scribe_delete(note_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    return {"ok": S(request).scribe.delete(ctx, note_id)}


@router.get("/scribe/{note_id}/audio")
async def scribe_audio(note_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    p = S(request).scribe.audio_path(ctx, note_id)
    if not p or not p.exists():
        raise HTTPException(404)
    return _range_file(p, request, "audio/webm" if p.suffix == ".webm" else "audio/mpeg")


@router.get("/scribe/{note_id}/export")
async def scribe_export(note_id: str, request: Request, ctx: Ctx = Depends(member_ctx)):
    svc = S(request)
    if not svc.scribe.get(ctx, note_id):
        raise HTTPException(404)
    f = svc.paths.notes / note_id / "transcript.md"
    if not f.exists():
        raise HTTPException(404, "Not ready yet")
    return FileResponse(f, media_type="text/markdown", filename=f"{note_id}.md")


# =========================================================================== lens
@router.post("/lens/ocr")
async def lens_ocr(request: Request, file: UploadFile = File(...), ctx: Ctx = Depends(get_ctx)):
    data = await file.read()
    try:
        return await asyncio.to_thread(S(request).lens.ocr_bytes, data)
    except Exception as e:
        raise HTTPException(400, f"Couldn't read that image: {e}")


# =========================================================================== sharing
@router.get("/share")
async def share_status(request: Request, ctx: Ctx = Depends(get_ctx)):
    return S(request).share.status(owner=ctx.is_owner)


@router.get("/share/qr")
async def share_qr(request: Request, kind: str = "url", ctx: Ctx = Depends(owner_ctx)):
    return Response(S(request).share.qr_svg(kind), media_type="image/svg+xml")


@router.post("/share/firewall")
async def share_firewall(request: Request, ctx: Ctx = Depends(owner_ctx)):
    if not is_local(request):
        raise HTTPException(403, "Approve this on the device.")
    return {"requested": await asyncio.to_thread(S(request).share.request_firewall_rule)}


class HotspotIn(BaseModel):
    on: bool


@router.post("/share/hotspot")
async def share_hotspot(body: HotspotIn, request: Request, ctx: Ctx = Depends(owner_ctx)):
    if not is_local(request):
        raise HTTPException(403)
    return await asyncio.to_thread(S(request).share.hotspot, body.on)


@public_router.get("/cert", include_in_schema=False)
async def ca_cert(request: Request):
    """The MIMI local certificate authority, for installing on phones."""
    der = await asyncio.to_thread(S(request).share.ca_der)
    return Response(der, media_type="application/x-x509-ca-cert", headers={"Content-Disposition": 'attachment; filename="MIMI-Local-CA.crt"'})


# =========================================================================== system
@router.get("/system")
async def system_info(request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    usage = await asyncio.to_thread(system.disk_usage, svc.paths)
    return {
        "version": __version__, "root": str(svc.paths.root), "hardware": svc.hw, "health": svc.health(), "disk": usage,
        "autostart": system.autostart_enabled(), "shell_built": system.shell_exe(svc.paths).exists(), "portable": svc.paths.portable,
        "logs": sorted(p.name for p in svc.paths.logs.glob("*.log")),
    }


@router.get("/system/logs/{name}")
async def system_log(name: str, request: Request, lines: int = 200, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    f = (svc.paths.logs / name).resolve()
    if f.parent != svc.paths.logs.resolve() or not f.exists():
        raise HTTPException(404)
    with open(f, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 200_000))
        text = fh.read().decode("utf-8", "replace")
    return PlainTextResponse("\n".join(text.splitlines()[-min(lines, 2000):]))


@router.post("/system/restart-services")
async def restart_services(request: Request, ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    await svc.kiwix_service.restart()
    svc.kiwix.invalidate()
    await svc.models.unload()
    asyncio.create_task(svc.models.preload())
    return {"ok": True}


@router.post("/system/open-folder")
async def open_folder(request: Request, which: str = "root", ctx: Ctx = Depends(owner_ctx)):
    svc = S(request)
    if not is_local(request):
        raise HTTPException(403)
    target = {"root": svc.paths.root, "logs": svc.paths.logs, "zim": svc.paths.zim, "data": svc.paths.data, "library": svc.paths.library, "tools": svc.paths.root / "tools"}.get(which)
    if not target:
        raise HTTPException(404)
    system.open_folder(target)
    return {"ok": True}


@router.post("/system/shutdown")
async def shutdown(request: Request):
    if not is_local(request):
        raise HTTPException(403)
    svc = S(request)

    async def later():
        await asyncio.sleep(0.3)
        await svc.shutdown_hook()

    asyncio.create_task(later())
    return {"ok": True}
