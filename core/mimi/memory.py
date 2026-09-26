"""Personal memory: small, transparent, user-controlled facts about each user.

* Memories are created explicitly ("remember that…") or suggested by MIMI via
  the `remember` tool. With the default "ask" setting, suggestions wait for the
  user's approval (a chip in the chat and the Memory page).
* Relevant memories are injected into the system prompt each turn; the reply
  records exactly which ones were used so the UI can show "Memory used".
"""

from __future__ import annotations

import re

import numpy as np

from . import db as dbm
from . import log
from .auth import Ctx
from .events import EventBus
from .llm import ModelManager, from_blob, to_blob
from .settings import SettingsStore

L = log.get("memory")
CATEGORIES = ("personal", "preference", "project", "other")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", t.lower()).strip()


def public(m: dict) -> dict:
    return {k: m[k] for k in ("id", "text", "category", "status", "pinned", "source_chat_id", "created_at", "updated_at", "last_used_at", "use_count")}


class MemoryService:
    def __init__(self, db: dbm.Database, models: ModelManager, events: EventBus, settings: SettingsStore):
        self.db = db
        self.models = models
        self.events = events
        self.settings = settings

    # --- policy ---------------------------------------------------------------
    def mode(self, ctx: Ctx) -> str:
        if ctx.is_guest:
            return "off"
        p = self.settings.user(ctx.id, "privacy", ctx.role)
        return "off" if p.memory_paused else p.memory

    def enabled_for(self, ctx: Ctx) -> bool:
        return self.mode(ctx) != "off"

    # --- CRUD -----------------------------------------------------------------
    def list(self, user_id: str, status: str | None = None, q: str | None = None) -> list[dict]:
        sql = "SELECT * FROM memories WHERE user_id=?"
        params: list = [user_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        if q:
            sql += " AND text LIKE ?"
            params.append(f"%{q}%")
        sql += " ORDER BY pinned DESC, updated_at DESC"
        return [public(m) for m in self.db.all(sql, tuple(params))]

    def get(self, user_id: str, mem_id: str) -> dict | None:
        return self.db.one("SELECT * FROM memories WHERE id=? AND user_id=?", (mem_id, user_id))

    async def add(self, user_id: str, text: str, category: str = "other", status: str = "active", *,
                  source_chat_id: str | None = None, source_message_id: str | None = None, pinned: bool = False) -> dict:
        text = text.strip()[:500]
        if not text:
            raise ValueError("Memory text is empty")
        category = category if category in CATEGORIES else "other"
        emb = await self._embed(text)
        m = {
            "id": dbm.new_id("m_"), "user_id": user_id, "text": text, "category": category, "status": status, "pinned": int(pinned),
            "source_chat_id": source_chat_id, "source_message_id": source_message_id, "embedding": to_blob(emb) if emb is not None else None,
            "created_at": dbm.now(), "updated_at": dbm.now(),
        }
        self.db.execute(
            "INSERT INTO memories(id,user_id,text,category,status,pinned,source_chat_id,source_message_id,embedding,created_at,updated_at) "
            "VALUES(:id,:user_id,:text,:category,:status,:pinned,:source_chat_id,:source_message_id,:embedding,:created_at,:updated_at)", m)
        out = public(self.get(user_id, m["id"]))  # type: ignore[arg-type]
        self.events.publish("memory.changed", {"id": m["id"], "status": status}, user_id=user_id)
        return out

    async def update(self, user_id: str, mem_id: str, *, text: str | None = None, category: str | None = None,
                     pinned: bool | None = None, status: str | None = None) -> dict | None:
        m = self.get(user_id, mem_id)
        if not m:
            return None
        sets, params = ["updated_at=?"], [dbm.now()]
        if text is not None and text.strip() and text.strip() != m["text"]:
            emb = await self._embed(text.strip())
            sets += ["text=?", "embedding=?"]
            params += [text.strip()[:500], to_blob(emb) if emb is not None else None]
        if category is not None and category in CATEGORIES:
            sets.append("category=?"); params.append(category)
        if pinned is not None:
            sets.append("pinned=?"); params.append(int(pinned))
        if status in ("active", "suggested"):
            sets.append("status=?"); params.append(status)
        params += [mem_id, user_id]
        self.db.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=? AND user_id=?", tuple(params))
        self.events.publish("memory.changed", {"id": mem_id}, user_id=user_id)
        return public(self.get(user_id, mem_id))  # type: ignore[arg-type]

    def delete(self, user_id: str, mem_id: str) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id=? AND user_id=?", (mem_id, user_id))
        self.events.publish("memory.changed", {"id": mem_id, "deleted": True}, user_id=user_id)
        return cur.rowcount > 0

    def clear(self, user_id: str) -> int:
        cur = self.db.execute("DELETE FROM memories WHERE user_id=?", (user_id,))
        self.events.publish("memory.changed", {"cleared": True}, user_id=user_id)
        return cur.rowcount

    def export(self, user_id: str) -> list[dict]:
        return self.list(user_id)

    # --- the remember tool ------------------------------------------------------
    async def remember(self, ctx: Ctx, fact: str, category: str, chat_id: str | None, message_id: str | None) -> tuple[str, dict | None]:
        mode = self.mode(ctx)
        if mode == "off":
            return "off", None
        existing = await self._similar(ctx.id, fact)
        if existing:
            return "exists", public(existing)
        status = "active" if mode == "auto" else "suggested"
        mem = await self.add(ctx.id, fact, category, status, source_chat_id=chat_id, source_message_id=message_id)
        return ("saved" if status == "active" else "suggested"), mem

    async def _similar(self, user_id: str, text: str) -> dict | None:
        rows = self.db.all("SELECT * FROM memories WHERE user_id=?", (user_id,))
        n = _norm(text)
        for r in rows:
            if _norm(r["text"]) == n:
                return r
        emb = await self._embed(text)
        if emb is None:
            return None
        best, best_sim = None, 0.0
        for r in rows:
            v = from_blob(r["embedding"])
            if v is None or v.shape != emb.shape:
                continue
            sim = float(np.dot(v, emb))
            if sim > best_sim:
                best, best_sim = r, sim
        return best if best_sim >= 0.93 else None

    # --- retrieval --------------------------------------------------------------
    async def retrieve(self, ctx: Ctx, query: str, k: int = 6) -> list[dict]:
        if ctx.is_guest or self.settings.user(ctx.id, "privacy", ctx.role).memory_paused:
            return []
        rows = self.db.all("SELECT * FROM memories WHERE user_id=? AND status='active'", (ctx.id,))
        if not rows:
            return []
        if len(rows) <= 8:
            chosen = rows
        else:
            pinned = [r for r in rows if r["pinned"]]
            rest = [r for r in rows if not r["pinned"]]
            q = await self._embed(query)
            if q is None:
                chosen = pinned + sorted(rest, key=lambda r: r["updated_at"], reverse=True)[:k]
            else:
                scored = []
                for r in rest:
                    v = from_blob(r["embedding"])
                    if v is None:
                        v = await self._embed(r["text"])
                        if v is not None:
                            self.db.execute("UPDATE memories SET embedding=? WHERE id=?", (to_blob(v), r["id"]))
                    if v is not None and v.shape == q.shape:
                        scored.append((float(np.dot(v, q)), r))
                scored.sort(key=lambda x: x[0], reverse=True)
                chosen = pinned + [r for s, r in scored[:k] if s >= 0.30]
        ids = [r["id"] for r in chosen]
        if ids:
            self.db.execute(
                f"UPDATE memories SET last_used_at=?, use_count=use_count+1 WHERE id IN ({','.join('?' * len(ids))})",
                (dbm.now(), *ids),
            )
        return [{"id": r["id"], "text": r["text"], "category": r["category"]} for r in chosen]

    async def _embed(self, text: str) -> np.ndarray | None:
        try:
            return (await self.models.embed([text]))[0]
        except Exception as e:
            L.warning("memory embedding unavailable: %s", e)
            return None
