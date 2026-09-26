"""The user's own files and Scribe notes: text extraction, chunking, embeddings
and hybrid (keyword + vector) search.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import numpy as np

from . import db as dbm
from . import log
from .events import EventBus
from .llm import ModelManager, from_blob, to_blob
from .paths import Paths

L = log.get("docs")
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".html", ".htm", ".xml", ".yaml", ".yml", ".ini", ".rtf"}
MAX_BYTES = 60 * 1024 * 1024


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == ".docx":
        import docx

        d = docx.Document(str(path))
        return "\n\n".join(p.text for p in d.paragraphs if p.text.strip())
    if ext in (".html", ".htm"):
        from selectolax.parser import HTMLParser

        return HTMLParser(path.read_text("utf-8", errors="replace")).text(separator="\n")
    if ext in TEXT_EXT or ext == "":
        return path.read_text("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {ext or 'unknown'}")


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        while len(p) > size * 1.5:  # split giant paragraphs on sentence-ish boundaries
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 3 else size
            piece, p = p[:cut].strip(), p[cut:].strip()
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(piece)
        if len(cur) + len(p) + 2 <= size:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            cur = (cur[-overlap:] + "\n\n" + p) if cur and overlap else p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) > 20]


def _fts_query(q: str) -> str:
    toks = re.findall(r"[A-Za-z0-9]{2,}", q)
    return " OR ".join(f'"{t}"' for t in toks[:12])


class DocsService:
    def __init__(self, db: dbm.Database, models: ModelManager, events: EventBus, paths: Paths):
        self.db = db
        self.models = models
        self.events = events
        self.paths = paths
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._matrix: dict[str, tuple[list[int], np.ndarray]] = {}

    def start(self) -> None:
        # re-queue anything left mid-way by a previous run
        for d in self.db.all("SELECT id FROM docs WHERE status IN ('queued','indexing')"):
            self.queue.put_nowait(d["id"])
        self._worker = asyncio.create_task(self._run())

    def count(self, user_id: str) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM docs WHERE user_id=? AND status='ready'", (user_id,)) or 0)

    def list(self, user_id: str) -> list[dict]:
        return self.db.all("SELECT id,kind,source,title,size,status,error,chunks,created_at FROM docs WHERE user_id=? ORDER BY created_at DESC", (user_id,))

    async def add_upload(self, user_id: str, filename: str, data: bytes) -> dict:
        if len(data) > MAX_BYTES:
            raise ValueError("File is too large (60 MB max).")
        safe = re.sub(r"[^\w.\- ()]+", "_", Path(filename).name)[:120] or "file"
        ext = Path(safe).suffix.lower()
        if ext not in TEXT_EXT | {".pdf", ".docx"}:
            raise ValueError("Supported files: PDF, Word (.docx), text, Markdown, HTML, CSV.")
        doc_id = dbm.new_id("d_")
        dest = self.paths.library / user_id / f"{doc_id}_{safe}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        kind = "pdf" if ext == ".pdf" else ("docx" if ext == ".docx" else "text")
        self.db.execute(
            "INSERT INTO docs(id,user_id,kind,source,title,path,size,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (doc_id, user_id, kind, "upload", Path(safe).stem, str(dest), len(data), "queued", dbm.now()),
        )
        await self.queue.put(doc_id)
        return self.db.one("SELECT id,kind,source,title,size,status,chunks,created_at FROM docs WHERE id=?", (doc_id,))  # type: ignore[return-value]

    async def add_note(self, user_id: str, note_id: str, title: str, text: str) -> None:
        doc_id = f"note_{note_id}"
        dest = self.paths.notes / note_id / "transcript.md"
        self.db.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        self.db.execute(
            "INSERT INTO docs(id,user_id,kind,source,title,path,size,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (doc_id, user_id, "note", "scribe", title, str(dest), len(text), "queued", dbm.now()),
        )
        await self.queue.put(doc_id)

    def delete(self, user_id: str, doc_id: str) -> bool:
        d = self.db.one("SELECT * FROM docs WHERE id=? AND user_id=?", (doc_id, user_id))
        if not d:
            return False
        self.db.execute("DELETE FROM docs WHERE id=?", (doc_id,))
        if d["source"] == "upload" and d["path"]:
            try:
                Path(d["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._matrix.pop(user_id, None)
        self.events.publish("docs.changed", {"id": doc_id, "deleted": True}, user_id=user_id)
        return True

    # --- indexing -------------------------------------------------------------------
    async def _run(self) -> None:
        while True:
            doc_id = await self.queue.get()
            try:
                await self._index(doc_id)
            except Exception as e:
                L.exception("indexing %s failed", doc_id)
                self.db.execute("UPDATE docs SET status='error', error=? WHERE id=?", (str(e)[:300], doc_id))
                d = self.db.one("SELECT user_id FROM docs WHERE id=?", (doc_id,))
                if d:
                    self.events.publish("docs.changed", {"id": doc_id, "status": "error"}, user_id=d["user_id"])

    async def _index(self, doc_id: str) -> None:
        d = self.db.one("SELECT * FROM docs WHERE id=?", (doc_id,))
        if not d:
            return
        self.db.execute("UPDATE docs SET status='indexing' WHERE id=?", (doc_id,))
        self.events.publish("docs.changed", {"id": doc_id, "status": "indexing"}, user_id=d["user_id"])
        text = await asyncio.to_thread(extract_text, Path(d["path"]))
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("No readable text found in this file.")
        vecs = await self.models.embed(chunks)
        with self.db.tx() as c:
            c.execute("DELETE FROM doc_chunks WHERE doc_id=?", (doc_id,))
            c.executemany("INSERT INTO doc_chunks(doc_id, idx, text, embedding) VALUES(?,?,?,?)",
                          [(doc_id, i, t, to_blob(v)) for i, (t, v) in enumerate(zip(chunks, vecs))])
            c.execute("UPDATE docs SET status='ready', chunks=?, error=NULL WHERE id=?", (len(chunks), doc_id))
        self._matrix.pop(d["user_id"], None)
        self.events.publish("docs.changed", {"id": doc_id, "status": "ready"}, user_id=d["user_id"])
        L.info("indexed %s (%d chunks)", d["title"], len(chunks))

    # --- search -----------------------------------------------------------------------
    def _user_matrix(self, user_id: str) -> tuple[list[int], np.ndarray]:
        if user_id not in self._matrix:
            rows = self.db.all(
                "SELECT c.id, c.embedding FROM doc_chunks c JOIN docs d ON d.id=c.doc_id WHERE d.user_id=? AND d.status='ready'",
                (user_id,),
            )
            ids = [r["id"] for r in rows if r["embedding"]]
            mat = np.vstack([from_blob(r["embedding"]) for r in rows if r["embedding"]]) if ids else np.zeros((0, 1024), np.float32)
            self._matrix[user_id] = (ids, mat)
        return self._matrix[user_id]

    async def search(self, user_id: str, query: str, k: int = 5) -> list[dict]:
        ranks: dict[int, float] = {}
        fq = _fts_query(query)
        if fq:
            rows = self.db.all(
                "SELECT c.id FROM doc_chunks_fts f JOIN doc_chunks c ON c.id=f.rowid JOIN docs d ON d.id=c.doc_id "
                "WHERE doc_chunks_fts MATCH ? AND d.user_id=? ORDER BY bm25(doc_chunks_fts) LIMIT 20",
                (fq, user_id),
            )
            for r, row in enumerate(rows):
                ranks[row["id"]] = ranks.get(row["id"], 0) + 1 / (60 + r)
        ids, mat = self._user_matrix(user_id)
        if ids:
            try:
                q = (await self.models.embed([query]))[0]
                sims = mat @ q
                order = np.argsort(-sims)[:20]
                for r, idx in enumerate(order):
                    if sims[idx] < 0.25:
                        break
                    cid = ids[int(idx)]
                    ranks[cid] = ranks.get(cid, 0) + 1 / (60 + r)
            except Exception as e:
                L.warning("vector search unavailable: %s", e)
        if not ranks:
            return []
        best = sorted(ranks.items(), key=lambda x: -x[1])[:k]
        out = []
        for cid, score in best:
            row = self.db.one("SELECT c.id, c.text, c.doc_id, d.title, d.kind, d.source FROM doc_chunks c JOIN docs d ON d.id=c.doc_id WHERE c.id=?", (cid,))
            if row:
                note_id = row["doc_id"][5:] if row["doc_id"].startswith("note_") else None
                out.append({
                    "chunk_id": row["id"], "doc_id": row["doc_id"], "title": row["title"], "kind": row["kind"], "text": row["text"],
                    "score": score, "url": f"/scribe/{note_id}" if note_id else f"/library/files?doc={row['doc_id']}",
                })
        return out

    def purge_user(self, user_id: str) -> None:
        shutil.rmtree(self.paths.library / user_id, ignore_errors=True)
