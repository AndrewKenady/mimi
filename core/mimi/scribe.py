"""Scribe: record or upload audio → transcript with timestamps → summary, key
points and action items → a searchable note that MIMI can recall in chat.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path

from . import db as dbm
from . import log
from .auth import Ctx

L = log.get("scribe")

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "key_points", "action_items"],
}

SUMMARY_PROMPT = """You are summarizing a transcript recorded with MIMI's Scribe.
Return JSON with:
- "title": a specific 3–7 word title
- "summary": 2–4 sentences
- "key_points": up to 6 short bullets
- "action_items": concrete tasks with owners/dates if mentioned (empty list if none)

Transcript:
{transcript}"""


def fmt_ts(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class ScribeService:
    def __init__(self, svc):
        self.svc = svc
        self.db: dbm.Database = svc.db
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        for n in self.db.all("SELECT id FROM notes WHERE status IN ('queued','transcribing','summarizing')"):
            self.queue.put_nowait(n["id"])
        self._worker = asyncio.create_task(self._run())

    # --- CRUD -----------------------------------------------------------------------------
    def _public(self, n: dict, full: bool = False) -> dict:
        out = {k: n[k] for k in ("id", "title", "status", "progress", "duration", "error", "created_at", "updated_at")}
        out["summary"] = dbm.loads(n.get("summary"), None)
        out["audio_url"] = f"/api/scribe/{n['id']}/audio" if n.get("audio_path") else None
        if full:
            out["transcript"] = dbm.loads(n.get("transcript"), [])
        else:
            segs = dbm.loads(n.get("transcript"), [])
            out["preview"] = " ".join(s["text"] for s in segs[:6])[:200]
        return out

    def list(self, ctx: Ctx) -> list[dict]:
        return [self._public(n) for n in self.db.all("SELECT * FROM notes WHERE user_id=? ORDER BY created_at DESC", (ctx.id,))]

    def get(self, ctx: Ctx, note_id: str) -> dict | None:
        n = self.db.one("SELECT * FROM notes WHERE id=? AND user_id=?", (note_id, ctx.id))
        return self._public(n, full=True) if n else None

    def audio_path(self, ctx: Ctx, note_id: str) -> Path | None:
        n = self.db.one("SELECT audio_path FROM notes WHERE id=? AND user_id=?", (note_id, ctx.id))
        return Path(n["audio_path"]) if n and n["audio_path"] else None

    def rename(self, ctx: Ctx, note_id: str, title: str) -> dict | None:
        self.db.execute("UPDATE notes SET title=?, updated_at=? WHERE id=? AND user_id=?", (title.strip()[:120], dbm.now(), note_id, ctx.id))
        return self.get(ctx, note_id)

    def delete(self, ctx: Ctx, note_id: str) -> bool:
        cur = self.db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, ctx.id))
        if cur.rowcount:
            self.db.execute("DELETE FROM docs WHERE id=?", (f"note_{note_id}",))
            shutil.rmtree(self.svc.paths.notes / note_id, ignore_errors=True)
        return cur.rowcount > 0

    async def create(self, ctx: Ctx, filename: str, data: bytes, title: str | None = None) -> dict:
        if ctx.is_guest:
            raise PermissionError("Scribe isn't available to guests.")
        note_id = dbm.new_id("n_")
        folder = self.svc.paths.notes / note_id
        folder.mkdir(parents=True, exist_ok=True)
        ext = Path(filename or "audio.webm").suffix.lower() or ".webm"
        audio = folder / f"audio{ext}"
        audio.write_bytes(data)
        default_title = title or time.strftime("Recording, %b %d %I:%M %p").replace(" 0", " ")
        self.db.execute(
            "INSERT INTO notes(id,user_id,title,status,progress,audio_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (note_id, ctx.id, default_title, "queued", 0, str(audio), dbm.now(), dbm.now()),
        )
        await self.queue.put(note_id)
        self._emit(ctx.id, note_id)
        return self.get(ctx, note_id)  # type: ignore[return-value]

    def _emit(self, user_id: str, note_id: str) -> None:
        n = self.db.one("SELECT * FROM notes WHERE id=?", (note_id,))
        if n:
            self.svc.events.publish("scribe", self._public(n), user_id=user_id)

    # --- worker ---------------------------------------------------------------------------
    async def _run(self) -> None:
        while True:
            note_id = await self.queue.get()
            try:
                await self._process(note_id)
            except Exception as e:
                L.exception("scribe %s failed", note_id)
                self.db.execute("UPDATE notes SET status='error', error=?, updated_at=? WHERE id=?", (str(e)[:300], dbm.now(), note_id))
                n = self.db.one("SELECT user_id FROM notes WHERE id=?", (note_id,))
                if n:
                    self._emit(n["user_id"], note_id)

    async def _process(self, note_id: str) -> None:
        n = self.db.one("SELECT * FROM notes WHERE id=?", (note_id,))
        if not n:
            return
        user_id = n["user_id"]
        role = (self.db.one("SELECT role FROM users WHERE id=?", (user_id,)) or {}).get("role", "user")
        model = self.svc.settings.user(user_id, "voice", role).stt_model
        self.db.execute("UPDATE notes SET status='transcribing', progress=0, updated_at=? WHERE id=?", (dbm.now(), note_id))
        self._emit(user_id, note_id)
        loop = asyncio.get_running_loop()
        last_emit = [0.0]

        def on_progress(p: float) -> None:
            self.db.execute("UPDATE notes SET progress=? WHERE id=?", (round(p * 0.85, 3), note_id))
            if time.time() - last_emit[0] > 1.0:
                last_emit[0] = time.time()
                loop.call_soon_threadsafe(self._emit, user_id, note_id)

        def work():
            segs, duration = [], 0.0
            for seg, meta in self.svc.voice.transcribe_iter(Path(n["audio_path"]), model=model, on_progress=on_progress):
                segs.append(seg)
                duration = meta.get("duration", duration)
            return segs, duration

        segs, duration = await asyncio.to_thread(work)
        self.db.execute("UPDATE notes SET transcript=?, duration=?, progress=0.86, status='summarizing', updated_at=? WHERE id=?",
                        (dbm.dumps(segs), duration, dbm.now(), note_id))
        self._emit(user_id, note_id)
        text = " ".join(s["text"] for s in segs).strip()
        summary = await self._summarize(text) if text else {"title": "", "summary": "No speech detected.", "key_points": [], "action_items": []}
        title = n["title"]
        if summary.get("title") and n["title"].startswith("Recording"):
            title = summary["title"][:120]
        folder = self.svc.paths.notes / note_id
        md = [f"# {title}", "", f"_Recorded {time.strftime('%Y-%m-%d %H:%M', time.localtime(n['created_at']))} · {fmt_ts(duration)}_", ""]
        if summary.get("summary"):
            md += ["## Summary", summary["summary"], ""]
        if summary.get("key_points"):
            md += ["## Key points", *[f"- {p}" for p in summary["key_points"]], ""]
        if summary.get("action_items"):
            md += ["## Action items", *[f"- [ ] {p}" for p in summary["action_items"]], ""]
        md += ["## Transcript", *[f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs]]
        (folder / "transcript.md").write_text("\n".join(md), "utf-8")
        (folder / "transcript.json").write_text(json.dumps(segs, ensure_ascii=False), "utf-8")
        self.db.execute("UPDATE notes SET title=?, summary=?, status='ready', progress=1, updated_at=? WHERE id=?",
                        (title, dbm.dumps(summary), dbm.now(), note_id))
        self._emit(user_id, note_id)
        if text:
            await self.svc.docs.add_note(user_id, note_id, title, "\n".join(md))

    async def _summarize(self, text: str) -> dict:
        mm = self.svc.models
        spec = mm.model_for("main")
        if not spec:
            return {"title": "", "summary": "", "key_points": [], "action_items": []}
        limit = max(4000, int((mm.chat_ctx or spec.get("context", 8192)) * 3.0) - 3000)
        async with mm.gen_lock:
            if len(text) > limit:  # map: condense chunks, then reduce
                parts = [text[i : i + limit] for i in range(0, len(text), limit)]
                notes = []
                for p in parts[:8]:
                    notes.append(await mm.chat_once(spec, [{"role": "user", "content": f"Condense this transcript part into dense bullet notes:\n\n{p}"}], max_tokens=500, temperature=0.3))
                text = "\n".join(notes)
            raw = await mm.chat_once(spec, [{"role": "user", "content": SUMMARY_PROMPT.format(transcript=text[:limit])}],
                                     max_tokens=900, temperature=0.3, json_schema=SUMMARY_SCHEMA)
        try:
            data = json.loads(raw)
        except ValueError:
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {"title": "", "summary": raw.strip()[:800], "key_points": [], "action_items": []}
        return {
            "title": str(data.get("title") or "")[:120],
            "summary": str(data.get("summary") or ""),
            "key_points": [str(x) for x in (data.get("key_points") or [])][:8],
            "action_items": [str(x) for x in (data.get("action_items") or [])][:10],
        }
