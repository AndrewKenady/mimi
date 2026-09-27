"""Conversations: storage, branching, and the streaming tool-use loop.

A turn:
  1. store the user's message (with attachments),
  2. recall relevant memories and build a compact system prompt,
  3. stream the model; when it calls tools, run them (library search, memory,
     location…), feed results back, and continue — at most MAX_STEPS rounds,
  4. store the assistant message with its sources, tool trail, memories used
     and timings.
Everything streams to the client as Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator

from . import db as dbm
from . import log, persona, tools
from .auth import Ctx
from .llm import ModelError

L = log.get("chat")
MAX_STEPS = 4
CHARS_PER_TOKEN = 3.6


def est_tokens(obj: Any) -> int:
    if isinstance(obj, str):
        return int(len(obj) / CHARS_PER_TOKEN) + 1
    if isinstance(obj, list):
        return sum(est_tokens(p.get("text", "")) if isinstance(p, dict) and p.get("type") == "text" else (300 if isinstance(p, dict) else 0) for p in obj)
    return 0


def heuristic_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    for _ in range(3):  # "hey mimi, …" → "…"
        t = re.sub(r"^(hey|hi|hello|ok|okay|so|please|mimi)\b[,!.\s]+", "", t, flags=re.I)
    if len(t) <= 48:
        return t[:1].upper() + t[1:] if t else "New chat"
    cut = t[:48].rsplit(" ", 1)[0]
    return (cut[:1].upper() + cut[1:]).rstrip(",;:") + "…"


_CREATIVE = re.compile(r"\b(write|compose|draft|poem|story|haiku|joke|song|lyrics|limerick|rewrite|rephrase|translate|summari[sz]e (this|the following)|brainstorm|role.?play|pretend"
                       r"|(good|cute|cool|funny|clever) names?|names? (for|ideas)|what should i (name|call)|gift ideas)\b", re.I)
_CHITCHAT = re.compile(r"^\s*(hi|hey|hello|yo|thanks|thank you|ok(ay)?|cool|nice|good (morning|night|evening)|how are you|who are you|what can you do)\b[\s!.?]*$", re.I)
_QUESTION = re.compile(r"(\?\s*$)|^\s*(who|what|when|where|why|which|how|is|are|was|were|can|could|does|do|did|should|tell me|explain|define|describe|list|compare|give me|show me|find)\b", re.I)


def looks_factual(text: str) -> bool:
    """Heuristic: questions about the world should be grounded in the library."""
    t = (text or "").strip()
    if len(t) < 6 or _CHITCHAT.match(t) or _CREATIVE.search(t):
        return False
    if re.fullmatch(r"[\d\s.+\-*/^()%=x×÷]+", t):
        return False
    return bool(_QUESTION.search(t))


_REFLIST_HEADER = re.compile(r"(?mi)^\s*(\*\*)?(sources?|references?|citations?)(\*\*)?\s*:?\s*$[\s\S]*\Z")
_REFLIST_LINE = re.compile(r"(?m)^\s*\[\d+\][^\n]*$")


_MEM_STOP = set(
    "about after also always another because been being does doing drives during each from have having into just like likes "
    "lives love loves make made many more most much named called never often only other over person people prefer prefers "
    "really should some than that their them then there these they thing things this those through time times under until "
    "user usually very want wants well were what when where which while will with works would year years your".split()
)


def memories_referenced(memories: list[dict], answer: str) -> list[dict]:
    """The memories an answer actually drew on: one of the memory's distinctive words shows up in it.

    All of a user's memories may be in the context, but the "Memory used" chip should only
    appear when the reply leans on one (e.g. it names the Tacoma), not on every answer.
    """
    words = set(re.findall(r"[a-z][a-z'-]+", answer.lower()))
    stems = {w[:6] for w in words if len(w) >= 6}
    out = []
    for m in memories:
        keys = {w for w in re.findall(r"[a-z][a-z'-]+", m["text"].lower()) if len(w) >= 4 and w not in _MEM_STOP}
        if any(k in words or (len(k) >= 6 and k[:6] in stems) for k in keys):
            out.append(m)
    return out


def sanitize_citations(text: str, n_sources: int) -> str:
    """Drop invented citations: numbers with no matching source, and model-written reference lists."""
    text = _REFLIST_HEADER.sub("", text)
    text = _REFLIST_LINE.sub("", text)  # a line that is only "[1] ..." is a hand-made reference entry

    def fix(m: re.Match) -> str:
        nums = [x.strip() for x in m.group(1).split(",")]
        keep = [x for x in nums if x.isdigit() and 1 <= int(x) <= n_sources]
        return f"[{', '.join(keep)}]" if keep else ""

    text = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", fix, text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def drop_repeated_paragraphs(text: str) -> str:
    """Small models sometimes restate the whole answer after a tool call; keep the first telling."""
    paras = re.split(r"\n\s*\n", text)
    seen: list[set[str]] = []
    out = []
    for p in paras:
        words = set(re.findall(r"[a-z']{3,}", p.lower()))
        if len(words) >= 10 and any(len(words & s) / len(words | s) >= 0.55 for s in seen):
            continue
        if len(words) >= 10:
            seen.append(words)
        out.append(p)
    return "\n\n".join(out)


class ChatService:
    def __init__(self, svc):
        self.svc = svc
        self.db: dbm.Database = svc.db
        self.active: dict[str, asyncio.Event] = {}
        self.modes = persona.load_modes(svc.paths.config)

    # ------------------------------------------------------------------ CRUD
    def list(self, ctx: Ctx, q: str | None = None, archived: bool = False, project: str | None = None, limit: int = 200) -> list[dict]:
        if q:
            rows = self.db.all(
                "SELECT DISTINCT c.* FROM chats c LEFT JOIN messages_fts f ON f.chat_id=c.id AND messages_fts MATCH ? "
                "WHERE c.user_id=? AND c.temporary=0 AND (f.message_id IS NOT NULL OR c.title LIKE ?) ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ?",
                (self._fts(q), ctx.id, f"%{q}%", limit),
            )
        else:
            sql = "SELECT * FROM chats WHERE user_id=? AND temporary=0 AND archived=?"
            params: list = [ctx.id, int(archived)]
            if project:
                sql += " AND project=?"
                params.append(project)
            sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            rows = self.db.all(sql, tuple(params))
        for r in rows:
            last = self.db.one("SELECT content FROM messages WHERE id=?", (r["head_id"],)) if r.get("head_id") else None
            r["preview"] = re.sub(r"\s+", " ", (last or {}).get("content") or "")[:120]
        return rows

    @staticmethod
    def _fts(q: str) -> str:
        toks = re.findall(r"\w{2,}", q)
        return " ".join(f'"{t}"*' for t in toks[:8]) or '""'

    def projects(self, ctx: Ctx) -> list[str]:
        return [r["project"] for r in self.db.all("SELECT DISTINCT project FROM chats WHERE user_id=? AND project IS NOT NULL AND project!='' ORDER BY project", (ctx.id,))]

    def create(self, ctx: Ctx, *, title: str | None = None, mode: str | None = None, temporary: bool = False, project: str | None = None) -> dict:
        chat = {
            "id": dbm.new_id("c_"), "user_id": ctx.id, "title": title or "", "project": project, "mode": mode if mode in self.modes else None,
            "temporary": int(temporary or ctx.is_guest or not self.svc.settings.user(ctx.id, "privacy", ctx.role).history),
            "created_at": dbm.now(), "updated_at": dbm.now(),
        }
        self.db.execute(
            "INSERT INTO chats(id,user_id,title,project,mode,temporary,created_at,updated_at) VALUES(:id,:user_id,:title,:project,:mode,:temporary,:created_at,:updated_at)",
            chat,
        )
        return self.get_chat(ctx, chat["id"])  # type: ignore[return-value]

    def get_chat(self, ctx: Ctx, chat_id: str) -> dict | None:
        return self.db.one("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, ctx.id))

    def update(self, ctx: Ctx, chat_id: str, **fields) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in ("title", "project", "mode", "pinned", "archived") and v is not None}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self.db.execute(f"UPDATE chats SET {sets} WHERE id=? AND user_id=?", (*[int(v) if isinstance(v, bool) else v for v in allowed.values()], chat_id, ctx.id))
        return self.get_chat(ctx, chat_id)

    def delete(self, ctx: Ctx, chat_id: str) -> bool:
        self.db.execute("DELETE FROM messages_fts WHERE chat_id=?", (chat_id,))
        cur = self.db.execute("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, ctx.id))
        return cur.rowcount > 0

    def delete_all(self, ctx: Ctx) -> int:
        ids = [r["id"] for r in self.db.all("SELECT id FROM chats WHERE user_id=?", (ctx.id,))]
        for cid in ids:
            self.db.execute("DELETE FROM messages_fts WHERE chat_id=?", (cid,))
        cur = self.db.execute("DELETE FROM chats WHERE user_id=?", (ctx.id,))
        return cur.rowcount

    # ------------------------------------------------------------------ threads & branches
    def _msg(self, m: dict) -> dict:
        m = dict(m)
        m["meta"] = dbm.loads(m.get("meta"), {})
        return m

    def thread(self, chat_id: str, head_id: str | None) -> list[dict]:
        out: list[dict] = []
        cur = head_id
        guard = 0
        while cur and guard < 2000:
            m = self.db.one("SELECT * FROM messages WHERE id=? AND chat_id=?", (cur, chat_id))
            if not m:
                break
            out.append(self._msg(m))
            cur = m["parent_id"]
            guard += 1
        out.reverse()
        for m in out:
            sibs = self.db.all(
                "SELECT id FROM messages WHERE chat_id=? AND role=? AND parent_id IS ? ORDER BY created_at",
                (chat_id, m["role"], m["parent_id"]),
            )
            ids = [s["id"] for s in sibs]
            m["versions"] = {"ids": ids, "index": ids.index(m["id"]) if m["id"] in ids else 0, "count": len(ids)}
        return out

    def get_full(self, ctx: Ctx, chat_id: str) -> dict | None:
        chat = self.get_chat(ctx, chat_id)
        if not chat:
            return None
        chat["messages"] = self.thread(chat_id, chat.get("head_id"))
        return chat

    def switch_head(self, ctx: Ctx, chat_id: str, message_id: str) -> dict | None:
        chat = self.get_chat(ctx, chat_id)
        if not chat or not self.db.one("SELECT id FROM messages WHERE id=? AND chat_id=?", (message_id, chat_id)):
            return None
        cur = message_id
        while True:  # follow the most recent child down to a leaf
            child = self.db.one("SELECT id FROM messages WHERE chat_id=? AND parent_id=? ORDER BY created_at DESC LIMIT 1", (chat_id, cur))
            if not child:
                break
            cur = child["id"]
        self.db.execute("UPDATE chats SET head_id=? WHERE id=?", (cur, chat_id))
        return self.get_full(ctx, chat_id)

    def _insert(self, chat_id: str, parent_id: str | None, role: str, content: str, meta: dict, index: bool = True) -> dict:
        m = {"id": dbm.new_id("msg_"), "chat_id": chat_id, "parent_id": parent_id, "role": role, "content": content,
             "meta": dbm.dumps(meta), "created_at": dbm.now()}
        self.db.execute("INSERT INTO messages(id,chat_id,parent_id,role,content,meta,created_at) VALUES(:id,:chat_id,:parent_id,:role,:content,:meta,:created_at)", m)
        if index and content:
            self.db.execute("INSERT INTO messages_fts(content, chat_id, message_id) VALUES(?,?,?)", (content, chat_id, m["id"]))
        return self._msg(m)

    # ------------------------------------------------------------------ stop
    def stop(self, chat_id: str) -> bool:
        ev = self.active.get(chat_id)
        if ev:
            ev.set()
            return True
        return False

    # ------------------------------------------------------------------ attachments
    def _load_attachment(self, ctx: Ctx, upload_id: str) -> dict | None:
        return self.svc.uploads.get(ctx, upload_id)

    def _image_part(self, path: Path, max_side: int = 1024) -> dict | None:
        try:
            from PIL import Image, ImageOps

            img = Image.open(path)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=88)
            return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}
        except Exception as e:
            L.warning("could not read image %s: %s", path, e)
            return None

    # ------------------------------------------------------------------ the turn
    async def send(self, ctx: Ctx, chat_id: str | None, *, content: str, attachments: list[str] | None = None, mode: str | None = None,
                   role: str | None = None, voice: bool = False, regenerate: str | None = None, edit: str | None = None,
                   temporary: bool = False, think: bool | None = None) -> AsyncIterator[dict]:
        svc = self.svc
        content = (content or "").strip()
        if chat_id:
            chat = self.get_chat(ctx, chat_id)
            if not chat:
                yield {"event": "error", "data": {"message": "Chat not found"}}
                return
        else:
            chat = self.create(ctx, mode=mode, temporary=temporary)
            chat_id = chat["id"]
        mode_id = mode or chat.get("mode") or svc.settings.user(ctx.id, "assistant", ctx.role).default_mode
        if mode_id not in self.modes:
            mode_id = "everyday"
        if chat.get("mode") != mode_id:
            self.db.execute("UPDATE chats SET mode=? WHERE id=?", (mode_id, chat_id))
        mode_cfg = self.modes[mode_id]

        # --- guest rate limiting
        if ctx.is_guest:
            per_hour = svc.settings.device("sharing").guest_messages_per_hour
            sent = self.db.scalar(
                "SELECT COUNT(*) FROM messages m JOIN chats c ON c.id=m.chat_id WHERE c.user_id=? AND m.role='user' AND m.created_at>?",
                (ctx.id, time.time() - 3600),
            ) or 0
            if sent >= per_hour:
                yield {"event": "error", "data": {"message": "You've reached the guest message limit for this hour. Try again a bit later."}}
                return

        # --- figure out the user message (new / edit / regenerate)
        if regenerate:
            asst = self.db.one("SELECT * FROM messages WHERE id=? AND chat_id=?", (regenerate, chat_id))
            if not asst:
                yield {"event": "error", "data": {"message": "Message not found"}}
                return
            user_msg = self._msg(self.db.one("SELECT * FROM messages WHERE id=?", (asst["parent_id"],)))  # type: ignore[arg-type]
            content = user_msg["content"]
            attachments = user_msg["meta"].get("attachments_ids") or []
        else:
            if not content and not attachments:
                yield {"event": "error", "data": {"message": "Say something first."}}
                return
            parent = chat.get("head_id")
            if edit:
                old = self.db.one("SELECT * FROM messages WHERE id=? AND chat_id=?", (edit, chat_id))
                parent = old["parent_id"] if old else parent
            att_meta = []
            for aid in attachments or []:
                a = self._load_attachment(ctx, aid)
                if a:
                    att_meta.append({k: a[k] for k in ("id", "name", "kind", "url", "size")})
            user_msg = self._insert(chat_id, parent, "user", content, {"attachments": att_meta, "attachments_ids": [a["id"] for a in att_meta], "voice": voice},
                                    index=not chat["temporary"])
        self.db.execute("UPDATE chats SET head_id=?, updated_at=? WHERE id=?", (user_msg["id"], dbm.now(), chat_id))

        # --- model selection
        # Voice uses the resident main model too: short spoken replies are fast on it, and
        # swapping models on a 16 GB machine costs more time than it saves (battery saver
        # still maps "main" to the quick model).
        want_role = role if role in ("main", "quick", "reader") else "main"
        has_images = any((self._load_attachment(ctx, a) or {}).get("kind") == "image" for a in (attachments or []))
        spec = svc.models.model_for(want_role)
        if has_images and spec and not spec.vision:
            spec = svc.models.model_for("reader") or spec
        if not spec:
            yield {"event": "error", "data": {"message": "No language model is installed. Open Settings → Models."}}
            return
        asst_id = dbm.new_id("msg_")
        yield {"event": "meta", "data": {"chat_id": chat_id, "user_message": user_msg, "assistant_message_id": asst_id,
                                          "model": spec.id, "model_name": spec.name, "mode": mode_id, "title": chat.get("title") or ""}}

        cancel = asyncio.Event()
        self.active[chat_id] = cancel
        state = tools.TurnState(ctx=ctx, chat_id=chat_id, message_id=asst_id, query=content, mode=mode_cfg,
                                vision=spec.vision, temporary=bool(chat["temporary"]), voice=voice)
        t_start = time.time()
        answer = ""
        reasoning = ""
        trail: list[dict] = []
        timings: dict = {}
        error = None
        memories: list[dict] = []
        base_messages: list[dict] = []  # the prompt as the next turn will replay it (for the title call)
        first_tools: list[dict] | None = None
        try:
            # --- context: memories, location, system prompt, history
            if not chat["temporary"]:
                memories = await svc.memory.retrieve(ctx, content)
            general = svc.settings.device("general")
            loc = svc.location.describe()
            system = self._system_prompt(ctx, mode_id)
            context_note = user_msg["meta"].get("context") or persona.build_context(
                memories=memories, location=(loc or {}).get("description") or (loc or {}).get("label"), time_format=general.time_format,
                voice=voice)
            if not user_msg["meta"].get("context"):
                user_msg["meta"]["context"] = context_note
                self.db.execute("UPDATE messages SET meta=? WHERE id=?", (dbm.dumps(user_msg["meta"]), user_msg["id"]))
            thread = self.thread(chat_id, user_msg["parent_id"]) if user_msg["parent_id"] else []
            user_parts: list[dict] | str = f"{context_note}\n\n{content or '(see attachment)'}"
            extra_text = []
            image_parts = []
            for aid in attachments or []:
                a = self._load_attachment(ctx, aid)
                if not a:
                    continue
                if a["kind"] == "image":
                    if spec.vision:
                        part = self._image_part(Path(a["path"]))
                        if part:
                            image_parts.append(part)
                    else:
                        ocr = await asyncio.to_thread(svc.lens.ocr_path, Path(a["path"]))
                        extra_text.append(f"[Text read from the attached image “{a['name']}”]\n{ocr.get('text','')[:3000]}")
                else:
                    text = a.get("text") or ""
                    extra_text.append(f"[Attached file “{a['name']}”]\n{text[:6000]}")
            if extra_text:
                user_parts = f"{user_parts}\n\n" + "\n\n".join(extra_text)
            if image_parts:
                user_parts = [{"type": "text", "text": user_parts}] + image_parts

            max_out = 350 if voice else 1400
            budget = max(1024, (svc.models.chat_ctx or spec.get("context", 8192)) - max_out - est_tokens(system) - est_tokens(user_parts) - 900)
            history: list[dict] = []
            used = 0
            for m in reversed(thread):
                c = m["content"] or ""
                if m["role"] == "user":
                    if m["meta"].get("context"):  # replay exactly what the model saw, so its cache matches
                        c = f"{m['meta']['context']}\n\n{c}"
                    if m["meta"].get("attachments"):
                        c += " [attachment]"
                t = est_tokens(c) + 4
                if used + t > budget:
                    break
                history.insert(0, {"role": m["role"], "content": c})
                used += t
            messages: list[dict] = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user_parts}]
            base_messages = list(messages)

            # --- wait for the model (single generation slot)
            if svc.models.gen_lock.locked():
                svc.models.waiting += 1
                yield {"event": "status", "data": {"state": "queued", "label": "Waiting for MIMI to finish another answer…"}}
            async with svc.models.gen_lock:
                if svc.models.waiting:
                    svc.models.waiting = max(0, svc.models.waiting - 1)
                if not (svc.models.chat_model and svc.models.chat_model.id == spec.id and svc.models.chat_proc and svc.models.chat_proc.alive()):
                    yield {"event": "status", "data": {"state": "loading", "label": f"Waking up {spec.name}…"}}
                    await svc.models.ensure(spec)
                    budget_ctx = svc.models.chat_ctx
                    # re-trim history if the model came up with a smaller context
                    while len(messages) > 2 and sum(est_tokens(m.get("content") or "") for m in messages) + max_out > budget_ctx - 256:
                        messages.pop(1)
                yield {"event": "status", "data": {"state": "thinking", "label": "Thinking…"}}
                want_think = think if think is not None else svc.settings.device("models").think_harder
                must_ground = (svc.kiwix_service.alive() and looks_factual(content) and not image_parts
                               and mode_id != "storyteller")
                for step in range(MAX_STEPS):
                    avail = tools.schemas(state, svc) if step < MAX_STEPS - 1 else None
                    choice = "required" if (step == 0 and must_ground and avail) else "auto"
                    if step == 0:
                        first_tools = avail
                    step_text = ""
                    calls = None
                    async for ev in svc.models.chat_stream(spec, messages, tools=avail, max_tokens=max_out, think=bool(want_think),
                                                           cancel=cancel, tool_choice=choice):
                        if ev["type"] == "content":
                            step_text += ev["text"]
                            yield {"event": "delta", "data": {"text": ev["text"]}}
                        elif ev["type"] == "reasoning":
                            reasoning += ev["text"]
                            yield {"event": "reasoning", "data": {"text": ev["text"]}}
                        elif ev["type"] == "tool_calls":
                            calls = ev["calls"]
                        elif ev["type"] == "done":
                            timings = ev.get("timings") or timings
                    answer += step_text
                    if cancel.is_set() or not calls:
                        break
                    messages.append({"role": "assistant", "content": step_text or "",
                                     "tool_calls": [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}} for c in calls]})
                    images: list[str] = []
                    for c in calls:
                        tid = c["id"]
                        args = tools.parse_args(c["arguments"])
                        yield {"event": "tool", "data": {"id": tid, "name": c["name"], "state": "start", "args": args,
                                                         "label": _pending_label(c["name"], args)}}
                        t0 = time.time()
                        res = await tools.run(c["name"], c["arguments"], state, svc)
                        entry = {"id": tid, "name": c["name"], "state": "end", "label": res.label, "summary": res.summary, "ok": res.ok,
                                 "ms": int((time.time() - t0) * 1000), "data": res.data}
                        trail.append(entry)
                        yield {"event": "tool", "data": entry}
                        if res.sources:
                            yield {"event": "sources", "data": {"sources": state.sources}}
                        for me in state.memory_events:
                            yield {"event": "memory", "data": {"suggested" if me["status"] == "suggested" else "saved": [me["memory"]]}}
                        state.memory_events.clear()
                        messages.append({"role": "tool", "tool_call_id": tid, "content": res.text})
                        images.extend(res.images)
                    if images:
                        messages.append({"role": "user", "content": [{"type": "text", "text": "(Reference image(s) from the library, attached by MIMI for your analysis.)"}]
                                         + [{"type": "image_url", "image_url": {"url": u}} for u in images]})
                    if step_text and not step_text.endswith("\n"):
                        answer += "\n\n"
                        yield {"event": "delta", "data": {"text": "\n\n"}}
        except ModelError as e:
            error = str(e)
            L.warning("turn failed: %s", e)
        except Exception as e:  # never leave the client hanging
            error = "Something went wrong while answering."
            L.exception("turn crashed: %s", e)
        finally:
            self.active.pop(chat_id, None)

        answer = sanitize_citations(drop_repeated_paragraphs(answer), len(state.sources))
        used = memories_referenced(memories, answer)
        if used:
            svc.memory.mark_used([m["id"] for m in used])
            yield {"event": "memory", "data": {"used": used}}
        meta = {
            "model": spec.id, "model_name": spec.name, "mode": mode_id, "sources": state.sources, "tools": trail,
            "memories_used": used, "timings": {"total_ms": int((time.time() - t_start) * 1000), **{k: timings.get(k) for k in ("predicted_per_second", "prompt_per_second", "predicted_n", "prompt_n") if k in timings}},
            "voice": voice, "cancelled": cancel.is_set(), "error": error,
        }
        if reasoning and svc.settings.device("models").think_harder:
            meta["reasoning"] = reasoning[-4000:]
        asst_parent = user_msg["id"]
        m = {"id": asst_id, "chat_id": chat_id, "parent_id": asst_parent, "role": "assistant", "content": answer, "meta": dbm.dumps(meta), "created_at": dbm.now()}
        self.db.execute("INSERT INTO messages(id,chat_id,parent_id,role,content,meta,created_at) VALUES(:id,:chat_id,:parent_id,:role,:content,:meta,:created_at)", m)
        if answer and not chat["temporary"]:
            self.db.execute("INSERT INTO messages_fts(content, chat_id, message_id) VALUES(?,?,?)", (answer, chat_id, asst_id))
        self.db.execute("UPDATE chats SET head_id=?, updated_at=? WHERE id=?", (asst_id, dbm.now(), chat_id))
        title = chat.get("title") or ""
        if not title and content:
            title = heuristic_title(content)
            self.db.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))
            if base_messages and answer:
                asyncio.create_task(self._smart_title(ctx, chat_id, spec, base_messages + [{"role": "assistant", "content": answer}], first_tools))
        final = self.thread(chat_id, asst_id)[-1]
        if error:
            yield {"event": "error", "data": {"message": error, "message_id": asst_id}}
        yield {"event": "done", "data": {"message": final, "chat": {"id": chat_id, "title": title}}}

    def _system_prompt(self, ctx: Ctx, mode_id: str) -> str:
        svc = self.svc
        return persona.build_system_prompt(
            assistant=svc.settings.user(ctx.id, "assistant", ctx.role), user_name=None if ctx.is_guest else ctx.user["name"],
            mode=self.modes[mode_id] if mode_id != "everyday" else None, units=svc.settings.device("general").units,
            has_library=svc.kiwix_service.alive(), has_files=svc.docs.count(ctx.id) > 0,
        )

    async def warm(self) -> None:
        """Pre-fill the model server's prompt cache with the owner's system prompt and tools.

        That prefix is ~1.7k tokens (~13 s on the 780M). Processing it right after the model
        loads means the first question of the day starts answering in a second or two.
        """
        svc = self.svc
        mm = svc.models
        owner = self.db.one("SELECT * FROM users WHERE role='owner' ORDER BY created_at LIMIT 1")
        spec = mm.chat_model
        if not owner or not spec or mm.gen_lock.locked():
            return
        ctx = Ctx(dict(owner), None, True)
        mode_id = svc.settings.user(ctx.id, "assistant", ctx.role).default_mode
        mode_id = mode_id if mode_id in self.modes else "everyday"
        st = tools.TurnState(ctx=ctx, chat_id="", message_id="", query="", mode=self.modes[mode_id], vision=spec.vision)
        messages = [{"role": "system", "content": self._system_prompt(ctx, mode_id)}, {"role": "user", "content": "Hello"}]
        t0 = time.time()
        try:
            async with mm.gen_lock:
                await mm.chat_once(spec, messages, max_tokens=1, tools=tools.schemas(st, svc) or None, tool_choice="auto")
            L.info("prompt cache warmed in %.1f s", time.time() - t0)
        except Exception as e:
            L.debug("prompt cache warm-up skipped: %s", e)

    async def _smart_title(self, ctx: Ctx, chat_id: str, spec, convo: list[dict], tools_: list[dict] | None) -> None:
        """Ask the already-loaded model for a better title, only if it's idle.

        The request continues the conversation with the same system prompt and tools, so the
        model server's prompt cache still holds that shared prefix afterwards. A standalone
        title prompt would evict it and make the next chat reprocess ~1.7k tokens (~13 s).
        """
        await asyncio.sleep(0.5)
        mm = self.svc.models
        # If another answer is already running, wait for it (up to 3 min) rather than skip.
        for _ in range(180):
            if not mm.gen_lock.locked():
                break
            await asyncio.sleep(1)
        if mm.gen_lock.locked() or not mm.chat_model or mm.chat_model.id != spec.id:
            return
        try:
            async with mm.gen_lock:
                raw = await mm.chat_once(spec, convo + [{"role": "user", "content": persona.TITLE_FOLLOWUP}], max_tokens=24,
                                         temperature=0.3, tools=tools_, tool_choice="none")
            title = re.sub(r'["“”*#]', "", raw).strip().split("\n")[0][:60].rstrip(".")
            if 2 <= len(title) <= 60:
                self.db.execute("UPDATE chats SET title=? WHERE id=? AND user_id=?", (title, chat_id, ctx.id))
                self.svc.events.publish("chat.updated", {"id": chat_id, "title": title}, user_id=ctx.id)
        except Exception as e:
            L.debug("smart title skipped: %s", e)

    # ------------------------------------------------------------------ housekeeping
    def purge(self) -> None:
        """Drop temporary chats older than a day and apply per-user history retention."""
        self.db.execute("DELETE FROM chats WHERE temporary=1 AND updated_at < ?", (time.time() - 86400,))
        for u in self.db.all("SELECT id, role FROM users"):
            days = self.svc.settings.user(u["id"], "privacy", u["role"]).history_days
            if days:
                old = self.db.all("SELECT id FROM chats WHERE user_id=? AND pinned=0 AND updated_at < ?", (u["id"], time.time() - days * 86400))
                for c in old:
                    self.db.execute("DELETE FROM messages_fts WHERE chat_id=?", (c["id"],))
                    self.db.execute("DELETE FROM chats WHERE id=?", (c["id"],))


def _pending_label(name: str, args: dict) -> str:
    q = args.get("query") or args.get("title") or ""
    coll = tools.COLLECTION_NAMES.get(args.get("collection") or "auto", "the library")
    return {
        "search_library": f"Searching {coll} for “{q}”…",
        "read_article": f"Reading “{q}”…",
        "show_reference_image": f"Looking at a picture of “{q}”…",
        "search_my_files": f"Searching your files for “{q}”…",
        "remember": "Noting that…",
        "where_am_i": "Checking location…",
        "nearby_places": "Looking around…",
        "calculate": "Calculating…",
        "get_directions": f"Planning a route to {args.get('destination') or 'there'}…",
    }.get(name) or f"{(tools.PLUGINS[name].label if name in tools.PLUGINS else '') or 'Using ' + name}…"
