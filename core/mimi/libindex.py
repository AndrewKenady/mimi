"""Collections inside ZIMs, and a full-text index of the documents they hold.

Some ZIM families don't have readable HTML articles behind their main page:

* **nautilus** (`zimgit-*`: medicine, water, knots, food, post-disaster) — the
  home page is an empty `<ul id="doc-list">` that JavaScript fills from
  `database.js`; the content is PDFs (and sometimes video/audio) under
  `files/`. Kiwix's catalog says "1 article" and its Xapian index only covers
  the home page, so neither the reader nor chat grounding can reach the books.
* **TED** (`ted_*`) — the `index` page is a JS grid fed by
  `assets/data_<lang>.js` (older: `assets/data.js`); each talk is a real HTML
  page at `<slug>` with a `<video>`.
* **Gutenberg** (`gutenberg_*`) — `Home` is a JS table fed by
  `full_by_popularity.js` (`[title, author, formats, id, shelf]` rows); each
  book has a cover page `<title>_cover.<id>` (`.html` suffix before v3).

This module parses those data files into a list of `Doc`s (pure functions,
tested with fixtures), extracts PDF text page by page with pypdf, and keeps it
in a SQLite FTS5 index so documents can be searched and cited by page.

The index is a *cache* in its own file (`data/library-index.sqlite`), not part
of `mimi.db`: it is rebuilt from the ZIMs whenever they change, can be deleted
at any time, keeps bulk writes away from the chat database's lock, and stays
out of personal-data backups.
"""

from __future__ import annotations

import ast
import io
import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from posixpath import splitext
from typing import Any, Iterable

from . import log

L = log.get("libindex")
SCHEMA_VERSION = 1

# Biggest document we will pull into memory to extract text from.
MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_PDF_PAGES = 3000

MIME_BY_EXT = {
    ".pdf": "application/pdf", ".epub": "application/epub+zip", ".mp4": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg",
    ".mkv": "video/x-matroska", ".mov": "video/quicktime", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".oga": "audio/ogg",
    ".opus": "audio/ogg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".flac": "audio/flac", ".txt": "text/plain",
    ".html": "text/html", ".htm": "text/html", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml", ".zip": "application/zip", ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def mime_of(path: str, fallback: str = "application/octet-stream") -> str:
    return MIME_BY_EXT.get(splitext(path.split("#")[0].lower())[1], fallback)


def kind_of_mime(mime: str) -> str:
    """pdf | video | audio | image | html | text | epub | file"""
    m = (mime or "").split(";")[0].strip().lower()
    if m == "application/pdf":
        return "pdf"
    if m.startswith("video/"):
        return "video"
    if m.startswith("audio/"):
        return "audio"
    if m.startswith("image/"):
        return "image"
    if m in ("text/html", "application/xhtml+xml"):
        return "html"
    if m.startswith("text/"):
        return "text"
    if m == "application/epub+zip":
        return "epub"
    return "file"


def is_document_path(path: str) -> bool:
    """True for paths whose extension says "not an HTML article" (PDFs, media, EPUBs…)."""
    ext = splitext(path.split("#")[0].lower())[1]
    return ext in MIME_BY_EXT and MIME_BY_EXT[ext] not in ("text/html",)


@dataclass
class Doc:
    """One item of a collection book: a PDF, a talk, a Project Gutenberg title…"""
    id: str
    title: str
    path: str                  # ZIM path to open (a file for nautilus, an HTML page for TED/Gutenberg)
    kind: str = "file"         # pdf | video | audio | html | epub | file
    author: str = ""
    description: str = ""
    mime: str = ""
    size: int = 0
    thumb: str = ""            # ZIM path of a thumbnail, if any
    pages: int = 0             # filled from the index for PDFs
    indexed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- data files
def parse_js_data(text: str) -> Any:
    """The literal assigned in a JS data file (`var DATABASE = [...]`, `window.json_data = {...}`).

    nautilus writes Python-repr-like literals (single quotes); TED and
    Gutenberg write JSON. Try JSON first, then a safe Python literal parse with
    JS keywords mapped. Never evaluates code. Returns None when it can't parse.
    """
    m = re.search(r"=\s*", text)
    if not m:
        return None
    body = text[m.end():].strip().rstrip(";").strip()
    if not body or body[0] not in "[{":
        return None
    try:
        return json.loads(body)
    except ValueError:
        pass
    py = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", re.sub(r"\bnull\b", "None", body)))
    try:
        return ast.literal_eval(py)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def _s(v: Any) -> str:
    if isinstance(v, list):  # TED titles/descriptions: [{"lang": "en", "text": "…"}]
        for it in v:
            if isinstance(it, dict) and it.get("lang") in ("en", "eng"):
                return _s(it.get("text"))
        return _s(v[0]) if v else ""
    if isinstance(v, dict):
        return _s(v.get("text") or v.get("name") or "")
    return re.sub(r"\s+", " ", str(v or "")).strip()


def nautilus_docs(database_js: str, files_prefix: str = "files/") -> list[Doc]:
    """Documents from a nautilus `database.js`: {_id, ti, dsc, aut, fp: [file, …]}."""
    data = parse_js_data(database_js)
    if not isinstance(data, list):
        return []
    out: list[Doc] = []
    for i, d in enumerate(data):
        if not isinstance(d, dict):
            continue
        files = d.get("fp") or []
        if isinstance(files, str):
            files = [files]
        files = [f for f in files if isinstance(f, str) and f]
        title = _s(d.get("ti")) or (files[0] if files else f"Document {i + 1}")
        for j, f in enumerate(files or [""]):
            if not f:
                continue
            path = f if f.startswith(files_prefix) or "://" in f else files_prefix + f.lstrip("/")
            mime = mime_of(path)
            out.append(Doc(
                id=f"{d.get('_id', i)}" + (f"-{j}" if len(files) > 1 else ""),
                title=title if len(files) == 1 else f"{title} ({j + 1} of {len(files)})",
                path=path, kind=kind_of_mime(mime), author=_s(d.get("aut")), description=_s(d.get("dsc")), mime=mime,
            ))
    return out


def ted_language_codes(index_html: str) -> list[str]:
    """Language codes offered by a TED home page's <select id="language-select">."""
    sel = re.search(r'<select[^>]*id="language-select"[^>]*>(.*?)</select>', index_html, re.S | re.I)
    return re.findall(r'<option[^>]*value="([^"]+)"', sel.group(1)) if sel else []


def ted_docs(data: Any) -> list[Doc]:
    """Talks from TED's `window.json_data` (a list of {id, slug, title, speaker, …})."""
    if isinstance(data, dict):  # some versions wrap the list
        data = data.get("videos") or data.get("json_data") or []
    if not isinstance(data, list):
        return []
    out = []
    for d in data:
        if not isinstance(d, dict) or not d.get("slug"):
            continue
        vid = str(d.get("id") or d["slug"])
        out.append(Doc(id=vid, title=_s(d.get("title")) or d["slug"].replace("_", " "), path=str(d["slug"]), kind="video",
                       author=_s(d.get("speaker")), description=_s(d.get("description"))[:400], mime="text/html",
                       thumb=f"videos/{vid}/thumbnail.webp"))
    return out


def gutenberg_docs(data: Any, html_suffix: bool = False) -> list[Doc]:
    """Books from Gutenberg's `full_by_popularity.js`: [title, author, "110", id, shelf] rows."""
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        title, author = _s(row[0]), _s(row[1])
        book_id = next((r for r in row[2:] if isinstance(r, int) or (isinstance(r, str) and r.isdigit() and len(r) != 3)), None)
        if not title or book_id is None:
            continue
        fs_title = title.strip().replace("/", "-")[:230]
        path = f"{fs_title}_cover.{book_id}" + (".html" if html_suffix else "")
        out.append(Doc(id=str(book_id), title=title, path=path, kind="html", author=author, mime="text/html"))
    return out


# --------------------------------------------------------------------------- PDF text
def page_label(page: int, label: str) -> str:
    """The page number to show in a citation: the printed label when there is one."""
    label = (label or "").strip()
    return label if label and len(label) <= 12 else str(page)


def pdf_pages(data: bytes, max_pages: int = MAX_PDF_PAGES) -> list[tuple[int, str, str]]:
    """[(page number from 1, printed page label, text)] for a PDF; empty pages skipped.

    The printed label ("112", "xiv", "w3") is what a reader sees on the paper
    (Where There Is No Doctor's physical page 50 is its printed page 3); the
    page number is what `#page=N` in a PDF viewer needs. A label table with
    repeats (numbering restarting per chapter) can't identify a page, so then
    every page is labelled by its physical number instead.
    """
    import pypdf

    for name in ("pypdf", "pypdf._reader", "pypdf.generic", "pypdf._cmap"):
        logging.getLogger(name).setLevel(logging.ERROR)  # malformed-but-readable PDFs are noisy
    reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
    try:
        labels = list(reader.page_labels)
    except Exception:
        labels = []
    if len(set(labels)) != len(labels):
        labels = []
    out = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = text.replace("\x00", "")
        if len(text.strip()) < 20:
            continue
        label = labels[i] if i < len(labels) and labels[i] else str(i + 1)
        out.append((i + 1, str(label), text))
    return out


def lower_priority() -> None:
    """Process-pool initializer: text extraction is background work; let everything else go first."""
    try:
        import psutil

        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS") else 10)
    except Exception:
        pass


# --------------------------------------------------------------------------- index
def fts_query(terms: Iterable[str], mode: str = "AND") -> str:
    """A safe FTS5 MATCH expression from plain words (each quoted, so no syntax leaks through)."""
    words = [re.sub(r'["*^:()]', "", t) for t in terms]
    words = [f'"{w}"' for w in words if w]
    return f" {mode} ".join(words)


class DocIndex:
    """SQLite FTS5 index of document pages, keyed by (zim name, path, page).

    Page 0 of each document holds its title/author/description, so documents
    without extractable text (scans, videos) are still found by title.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else path
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._setup()

    def _setup(self) -> None:
        with self._lock:
            v = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if v != SCHEMA_VERSION:  # a cache: start over rather than migrate
                for t in ("pages", "docs", "zims"):
                    self.conn.execute(f"DROP TABLE IF EXISTS {t}")
            self.conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS zims (
                    name TEXT PRIMARY KEY, signature TEXT, kind TEXT, items INTEGER, info TEXT, updated_at REAL);
                CREATE TABLE IF NOT EXISTS docs (
                    zim TEXT NOT NULL, path TEXT NOT NULL, title TEXT, signature TEXT, status TEXT, pages INTEGER DEFAULT 0,
                    error TEXT, updated_at REAL, PRIMARY KEY (zim, path));
                CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
                    text, title, zim UNINDEXED, path UNINDEXED, page UNINDEXED, label UNINDEXED,
                    tokenize='porter unicode61 remove_diacritics 2');
                PRAGMA user_version={SCHEMA_VERSION};
            """)

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # --- per-ZIM facts (kind, item count, health) ----------------------------
    def zim_info(self, name: str) -> dict | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM zims WHERE name=?", (name,)).fetchone()
        if not r:
            return None
        d = dict(r)
        try:
            d["info"] = json.loads(d["info"] or "{}")
        except ValueError:
            d["info"] = {}
        return d

    def set_zim_info(self, name: str, signature: str, kind: str, items: int, info: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO zims(name, signature, kind, items, info, updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET signature=excluded.signature, kind=excluded.kind, items=excluded.items, "
                "info=excluded.info, updated_at=excluded.updated_at",
                (name, signature, kind, items, json.dumps(info), time.time()))

    # --- documents --------------------------------------------------------------
    def doc_status(self, zim: str, path: str) -> dict | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM docs WHERE zim=? AND path=?", (zim, path)).fetchone()
        return dict(r) if r else None

    def doc_statuses(self, zim: str) -> dict[str, dict]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM docs WHERE zim=?", (zim,)).fetchall()
        return {r["path"]: dict(r) for r in rows}

    def put_document(self, zim: str, doc: Doc, signature: str, pages: list[tuple[int, str, str]], status: str = "ready", error: str = "") -> None:
        """Replace a document's pages (page 0 = its metadata) in one transaction."""
        meta = " · ".join(x for x in (doc.title, doc.author, doc.description) if x)
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.execute("DELETE FROM pages WHERE zim=? AND path=?", (zim, doc.path))
                self.conn.execute("INSERT INTO pages(text, title, zim, path, page, label) VALUES(?,?,?,?,0,'')", (meta, doc.title, zim, doc.path))
                self.conn.executemany(
                    "INSERT INTO pages(text, title, zim, path, page, label) VALUES(?,?,?,?,?,?)",
                    [(t, doc.title, zim, doc.path, n, label) for n, label, t in pages])
                self.conn.execute(
                    "INSERT INTO docs(zim, path, title, signature, status, pages, error, updated_at) VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(zim, path) DO UPDATE SET title=excluded.title, signature=excluded.signature, status=excluded.status, "
                    "pages=excluded.pages, error=excluded.error, updated_at=excluded.updated_at",
                    (zim, doc.path, doc.title, signature, status, len(pages), error, time.time()))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def forget_except(self, keep: Iterable[str]) -> int:
        """Drop everything indexed for ZIMs that are no longer in the library."""
        keep = set(keep)
        with self._lock:
            gone = [r[0] for r in self.conn.execute("SELECT DISTINCT zim FROM docs UNION SELECT name FROM zims").fetchall() if r[0] not in keep]
            for z in gone:
                self.conn.execute("DELETE FROM pages WHERE zim=?", (z,))
                self.conn.execute("DELETE FROM docs WHERE zim=?", (z,))
                self.conn.execute("DELETE FROM zims WHERE name=?", (z,))
        return len(gone)

    def counts(self, zim: str) -> tuple[int, int]:
        """(documents with text, pages with text) for a ZIM."""
        with self._lock:
            r = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(pages),0) FROM docs WHERE zim=? AND status='ready' AND pages>0", (zim,)).fetchone()
        return int(r[0]), int(r[1])

    # --- search -------------------------------------------------------------------
    def search(self, terms: list[str], zims: list[str], limit: int = 20, path: str | None = None) -> list[dict]:
        """Best pages for the query: AND of the terms first, OR when that finds too little.

        Each row: zim, path, page, label, title, score (bm25, lower is better), snippet.
        """
        if not terms or not zims:
            return []
        out: list[dict] = []
        seen = set()
        for mode in ("AND", "OR"):
            if mode == "OR" and (len(out) >= limit or len(terms) < 2):
                break
            q = fts_query(terms, mode)
            sql = (f"SELECT zim, path, page, label, title, bm25(pages, 1.0, 2.0) AS score, "
                   f"snippet(pages, 0, '', '', ' … ', 24) AS snippet FROM pages "
                   f"WHERE pages MATCH ? AND zim IN ({','.join('?' * len(zims))})")
            params: list = [q, *zims]
            if path:
                sql += " AND path=?"
                params.append(path)
            sql += " ORDER BY score LIMIT ?"
            params.append(limit)
            try:
                with self._lock:
                    rows = self.conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as e:
                L.debug("fts query %r failed: %s", q, e)
                continue
            for r in rows:
                k = (r["zim"], r["path"], r["page"])
                if k not in seen:
                    seen.add(k)
                    out.append(dict(r))
        return out[:limit]

    def page_text(self, zim: str, path: str, page: int) -> dict | None:
        with self._lock:
            r = self.conn.execute("SELECT text, label, title, page FROM pages WHERE zim=? AND path=? AND page=?", (zim, path, page)).fetchone()
        return dict(r) if r else None
