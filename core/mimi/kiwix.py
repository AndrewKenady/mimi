"""Offline reference library: runs kiwix-serve over the ZIM collections and
turns its search/content APIs into LLM-ready passages and a clean reader view.

Not every ZIM is a set of HTML articles. Document collections (nautilus PDFs),
TED talks and Project Gutenberg have JavaScript-driven home pages that Mimi's
script-free reader can't run, so each book is *surveyed* in the background:
what kind it is, what it really holds, whether it opens and whether it can be
searched (`health`). PDF text is indexed once into SQLite FTS5 (libindex.py)
and fused with Xapian's results by retrieval.py.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, unquote, urljoin

import httpx
import psutil
from selectolax.parser import HTMLParser, Node

from . import i18n, log
from . import retrieval as R
from .events import EventBus
from .libindex import (Doc, DocIndex, MAX_PDF_BYTES, gutenberg_docs, is_document_path, kind_of_mime, lower_priority, nautilus_docs,
                       page_label, parse_js_data, pdf_pages, ted_docs, ted_language_codes)
from .paths import Paths
from .procs import ManagedProcess
from .settings import SettingsStore

L = log.get("kiwix")
PORT = int(os.environ.get("MIMI_KIWIX_PORT", "7620"))
IDLE_BEFORE_RESTART = 15  # seconds without a library request before kiwix-serve may be restarted to free memory
NS = {"a": "http://www.w3.org/2005/Atom"}

# Collection = a friendly grouping used by the UI and by the search tool.
COLLECTIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("medicine", "Medicine", ("mdwiki", "zimgit-medicine", "wikipedia_en_medicine", "wikipedia_es_medicine", "wikipedia_fr_medicine", "wikem")),
    ("encyclopedia", "Encyclopedia", ("wikipedia_",)),
    ("travel", "Travel", ("wikivoyage",)),
    ("repair", "Repair guides", ("ifixit",)),
    ("survival", "Survival", ("zimgit-",)),
    ("dictionary", "Dictionary", ("wiktionary",)),
    ("qa", "Q&A", ("stackexchange", "superuser", "serverfault", "askubuntu", "stackoverflow")),
    ("books", "Books", ("gutenberg",)),
    ("talks", "Talks", ("ted_",)),
    ("courses", "Courses", ("khan",)),
]
COLLECTION_LABELS = {k: label for k, label, _ in COLLECTIONS}
STOPWORDS = R.STOPWORDS

# What a book holds, for its card and its item count.
KIND_NOUNS = {"articles": ("article", "articles"), "documents": ("document", "documents"), "videos": ("talk", "talks"), "books": ("book", "books")}

# Latency budget for the optional semantic steps (see docs/DECISIONS.md D14).
RERANK_CANDIDATES = 20
RERANK_TIMEOUT = 1.2     # seconds for one embedding call: query + ≤ 20 snippets
PASSAGE_EMBED_CHUNKS = 8
PASSAGE_EMBED_TIMEOUT = 0.8
EMBED_RETRY_AFTER = 20.0  # after a failed call, don't try the embedding server again for this long

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]


def zim_expected_size(path: Path) -> int | None:
    """The size a ZIM file must have, from its header (None if it isn't a ZIM).

    The header records where the closing 16-byte MD5 sits, so a download that stopped
    early shows up without hashing a 100 GB file (same rule as scripts/fetch.zim_complete).
    """
    import struct

    try:
        with open(path, "rb") as f:
            head = f.read(80)
    except OSError:
        return None
    if len(head) < 80 or struct.unpack_from("<I", head, 0)[0] != 72173914:  # ZIM magic number
        return None
    return struct.unpack_from("<Q", head, 72)[0] + 16


def collection_of(name: str) -> str:
    n = name.lower()
    for key, _, pats in COLLECTIONS:
        if any(p in n for p in pats):
            return key
    return "other"


def alias_of(name: str) -> str:
    return re.sub(r"_\d{4}-\d{2}[a-z]?$", "", name)  # a re-release adds a letter: _2026-07c


def quote_path(path: str) -> str:
    return quote(path, safe="/:()%,_-.~!*'")


def _title_is_topic(title: str, query: str) -> bool:
    """A looked-up title is the question's topic when it holds at least half of the question's
    content words ("Capital of Australia" in "what is the capital of Australia"), or the question
    is one word. Shorter ones ("Since", "Warm It Up") are often just words of the question."""
    tn, qn = len(R.query_terms(title)), len(R.query_terms(query))
    return qn <= 1 or (tn >= 2 and 2 * tn >= qn)


@dataclass
class Book:
    id: str
    name: str          # content name used in URLs (e.g. wikipedia_en_all_maxi_2026-08)
    alias: str         # date-less alias (stable across updates)
    title: str
    summary: str
    language: str
    category: str
    tags: str
    flavour: str
    articles: int      # as the Kiwix catalog reports it (a nautilus ZIM says 1)
    media: int
    collection: str
    icon: str | None
    file: str = ""
    size: int = 0
    pictures: bool = True
    videos: bool = False
    kind: str = "articles"   # articles | documents (nautilus) | videos (TED) | books (Gutenberg)
    items: int = 0           # honest count of what a reader can open (documents, talks, books or articles)
    main: str = ""           # main page path, once known


@dataclass
class Hit:
    title: str
    path: str
    book: str
    book_title: str
    collection: str
    snippet: str
    words: int = 0
    score: float = 0.0
    page: int = 0       # PDF page (from 1) for document hits
    label: str = ""     # the page's printed label ("112", "xiv")
    language: str = ""  # the book's language, as Kiwix gives it ("eng", "spa", "fra")


@dataclass
class Passage:
    title: str
    book: str
    book_title: str
    collection: str
    path: str
    text: str
    image: str | None = None
    url: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Fetched:
    status: int
    ctype: str
    final: str
    length: int = 0
    text: str | None = None


# --------------------------------------------------------------------------- service
class KiwixService:
    """Owns the kiwix-serve process and restarts it when the ZIM set changes."""

    def __init__(self, paths: Paths, settings: SettingsStore, events: EventBus):
        self.paths = paths
        self.settings = settings
        self.events = events
        self.proc: ManagedProcess | None = None
        self.files: list[Path] = []
        self.incomplete: list[dict] = []  # ZIMs held back because their download didn't finish
        self._task: asyncio.Task | None = None
        self._client: KiwixClient | None = None
        self.started_at = 0.0
        self.last_used = 0.0  # time.monotonic() of the client's latest request

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{PORT}"

    def zim_files(self) -> list[Path]:
        dirs = [self.paths.zim] + [Path(d) for d in self.settings.device("knowledge").extra_zim_dirs]
        files: list[Path] = []
        incomplete: list[dict] = []
        for d in dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.zim")):
                if f.with_name(f.name + ".aria2").exists():  # still downloading
                    continue
                try:
                    if f.stat().st_size < 1024:
                        continue
                except OSError:
                    continue
                expected = zim_expected_size(f)
                if expected is None or f.stat().st_size != expected:
                    # Cut short (an interrupted download) or not a ZIM at all: kiwix-serve would list it and
                    # then fail on the missing part, so it is held back and the library says why.
                    incomplete.append({"file": f.name, "size": f.stat().st_size, "expected": expected or 0})
                    L.warning("skipping %s: %s", f.name, "not a ZIM file" if expected is None else
                              f"incomplete ({f.stat().st_size} of {expected} bytes)")
                    continue
                files.append(f)
        self.incomplete = incomplete
        # If a full edition exists, hide the small editions of the same language (top articles, the 100).
        full = {m.group(1) for f in files if (m := re.match(r"wikipedia_([a-z]{2,3})_all", f.name))}
        return [f for f in files if not ((m := re.match(r"wikipedia_([a-z]{2,3})_(100|top)", f.name)) and m.group(1) in full)]

    async def start(self) -> None:
        exe = self.paths.exe("kiwix", "kiwix-serve")
        self.files = self.zim_files()
        if not exe.exists():
            L.warning("kiwix-serve not found at %s", exe)
            return
        if not self.files:
            L.info("no ZIM files yet; kiwix-serve not started")
            self.events.publish("library", {"status": "empty", "books": 0}, sticky=True)
            return
        # A search sends kiwix-serve dozens of title lookups next to its full-text query; more threads
        # keep them from queueing behind each other (4 to 8, by core count).
        threads = max(4, min(8, os.cpu_count() or 4))
        args = [str(exe), "--address", "127.0.0.1", "--port", str(PORT), "--threads", str(threads), "-n", "-m", "-b", "-k", "-z",
                "--attachToProcess", str(os.getpid()), *[str(f) for f in self.files]]
        # libkiwix keeps every recent full-text search in memory, about 70 MB each over the English
        # books; on the F1 that reached 5 GB of commit in an hour and starved the model. Two is plenty:
        # Mimi doesn't page through results.
        self.proc = ManagedProcess("kiwix-serve", args, cwd=self.paths.root, log_path=self.paths.logs / "kiwix.log",
                                   env={"KIWIX_SEARCH_CACHE_SIZE": "2"})
        self.proc.start()
        async with httpx.AsyncClient() as c:
            for _ in range(100):
                try:
                    r = await c.get(f"{self.base}/catalog/v2/entries?count=1", timeout=2)
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.2)
        self.started_at = time.time()
        self.events.publish("library", {"status": "ready", "books": len(self.files)}, sticky=True)
        L.info("kiwix-serve ready with %d ZIM files", len(self.files))

    async def stop(self) -> None:
        if self._client:
            self._client.stop_background()
        if self.proc:
            await asyncio.to_thread(self.proc.stop)
            self.proc = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    def alive(self) -> bool:
        return bool(self.proc and self.proc.alive())

    # libkiwix holds on to memory as it searches (on the F1: 28-70 MB per full-text search, 4-5 GB within
    # an hour), and none of its cache settings bounds all of it. A fresh process gives it back.
    def memory(self) -> int:
        """kiwix-serve's committed memory in bytes (resident memory where the OS reports no commit), 0 if unknown."""
        try:
            info = psutil.Process(self.proc.pid).memory_info() if self.proc and self.proc.pid else None
        except psutil.Error:
            return 0
        return int(getattr(info, "private", 0) or info.rss) if info else 0

    @staticmethod
    def memory_limit() -> int:
        """The committed memory at which kiwix-serve is restarted: 12 % of RAM, at least 1.5 GB."""
        return max(int(1.5 * 2**30), int(0.12 * psutil.virtual_memory().total))

    def needs_fresh_start(self) -> bool:
        """Over its memory limit, and the library idle long enough that no search is cut short."""
        return self.alive() and time.monotonic() - self.last_used > IDLE_BEFORE_RESTART and self.memory() > self.memory_limit()

    async def fresh_start(self) -> None:
        """The same books in a new kiwix-serve; the client's survey and indexing carry on."""
        held = self.memory()
        if self.proc:
            await asyncio.to_thread(self.proc.stop)
            self.proc = None
        await self.start()
        L.info("restarted kiwix-serve to give back %.1f GB it was holding", held / 2**30)

    def watch(self, client: KiwixClient) -> None:
        self._client = client
        client.refresh()  # survey the books and index their documents in the background

        async def loop():
            while True:
                await asyncio.sleep(30)
                try:
                    current = self.zim_files()
                    if [f.name for f in current] != [f.name for f in self.files] or (self.files and not self.alive()):
                        L.info("ZIM set changed (%d → %d files); restarting kiwix-serve", len(self.files), len(current))
                        await self.restart()
                        client.invalidate()
                        client.refresh()
                    elif self.needs_fresh_start():
                        await self.fresh_start()
                except Exception as e:  # keep watching no matter what
                    L.warning("kiwix watcher: %s", e)

        self._task = asyncio.create_task(loop())


# --------------------------------------------------------------------------- client
class KiwixClient:
    def __init__(self, service: KiwixService, settings: SettingsStore, index: DocIndex | None = None, embedder: Embedder | None = None):
        self.service = service
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(connect=3, read=30, write=10, pool=5), event_hooks={"request": [self._used]})
        self._books: list[Book] | None = None
        self._books_at = 0.0
        self.index = index or DocIndex(service.paths.data / "library-index.sqlite")
        self.embedder: Embedder = embedder or self._http_embed
        # Told after each call to the running embedding server: on the F1 the model manager stopped it as idle
        # while every search used it, and searches went without it for most of a 5-hour eval run.
        self.on_embed: Callable[[], None] | None = None
        self._embed_down_until = 0.0
        self._qvecs: dict[str, list[float]] = {}
        self._docs: dict[str, list[Doc]] = {}        # book name → collection items
        self._survey: dict[str, dict] = {}           # book name → {kind, items, main, health}
        self._refresh_task: asyncio.Task | None = None
        self.index_state: dict = {"state": "idle", "done": 0, "total": 0, "current": ""}
        self.worker_process = True  # extract PDF text in a separate process (tests use a thread)
        self._pool: ProcessPoolExecutor | None = None
        self._looked_up: set[str] = set()

    async def _used(self, request: httpx.Request) -> None:
        self.service.last_used = time.monotonic()  # kiwix-serve is only restarted while nothing is asking it

    def invalidate(self) -> None:
        self._books = None

    def stop_background(self) -> None:
        """Stop surveying/indexing now (Core is shutting down or kiwix-serve is restarting)."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        pool, self._pool = self._pool, None
        if pool:  # don't make shutdown wait for a half-read PDF; it is redone next time
            for p in list((getattr(pool, "_processes", None) or {}).values()):
                try:
                    p.terminate()
                except Exception:
                    pass
            pool.shutdown(wait=False, cancel_futures=True)

    async def books(self, include_disabled: bool = False) -> list[Book]:
        if self._books is None or time.time() - self._books_at > 600:
            self._books = await self._fetch_books()
            self._books_at = time.time()
        for b in self._books:
            self._apply_survey(b)
        if include_disabled:
            return list(self._books)
        disabled = set(self.settings.device("knowledge").disabled_books)
        return [b for b in self._books if b.name not in disabled and b.alias not in disabled]

    def _apply_survey(self, b: Book) -> None:
        s = self._survey.get(b.name)
        if s is None and b.name not in self._looked_up:  # last run's findings, if this is the same ZIM file
            self._looked_up.add(b.name)
            row = self.index.zim_info(b.name)
            if row and row.get("signature") == self._signature(b):
                s = self._survey[b.name] = {"kind": row["kind"], "items": row["items"], **row["info"]}
                s.setdefault("health", {})["stale"] = True
        if s:
            b.kind, b.items, b.main = s.get("kind") or "articles", int(s.get("items") or 0), s.get("main") or ""
        if not b.items:
            b.items = b.articles

    @staticmethod
    def _signature(b: Book) -> str:
        return f"{b.id}:{b.size}"  # a ZIM's UUID changes with every build

    async def _fetch_books(self) -> list[Book]:
        if not self.service.alive():
            return []
        try:
            r = await self.http.get(f"{self.service.base}/catalog/v2/entries?count=-1")
            root = ET.fromstring(r.text)
        except Exception as e:
            L.warning("catalog fetch failed: %s", e)
            return []
        sizes = {f.stem: f.stat().st_size for f in self.service.files if f.exists()}
        out: list[Book] = []
        for e in root.findall("a:entry", NS):
            name = ""
            icon = None
            for link in e.findall("a:link", NS):
                if link.get("type") == "text/html":
                    name = (link.get("href") or "").rsplit("/", 1)[-1]
                elif "thumbnail" in (link.get("rel") or ""):
                    icon = "/kiwix" + (link.get("href") or "")
            if not name:
                continue
            tags = e.findtext("a:tags", "", NS)
            out.append(
                Book(
                    id=(e.findtext("a:id", "", NS) or "").replace("urn:uuid:", ""),
                    name=name,
                    alias=alias_of(name),
                    title=e.findtext("a:title", name, NS),
                    summary=e.findtext("a:summary", "", NS),
                    language=e.findtext("a:language", "", NS),
                    category=e.findtext("a:category", "", NS),
                    tags=tags,
                    flavour=e.findtext("a:flavour", "", NS),
                    articles=int(e.findtext("a:articleCount", "0", NS) or 0),
                    media=int(e.findtext("a:mediaCount", "0", NS) or 0),
                    collection=collection_of(name),
                    icon=icon,
                    file=name + ".zim",
                    size=sizes.get(name, 0),
                    pictures="_pictures:no" not in tags,
                    videos="_videos:yes" in tags,
                )
            )
        order = {k: i for i, (k, _, _) in enumerate(COLLECTIONS)}
        order["encyclopedia"] = -1
        out.sort(key=lambda b: (order.get(b.collection, 99), -b.articles))
        return out

    async def book(self, name: str) -> Book | None:
        books = await self.books(include_disabled=True)
        for b in books:
            if name in (b.name, b.alias):
                return b
        if name == "wikipedia":  # generic alias used by geotagged places
            return next((b for b in books if b.collection == "encyclopedia"), None)
        return None

    # --- survey: what each book really holds -----------------------------------
    def refresh(self, delay: float = 2.0) -> None:
        """(Re)survey every book and index document text, in the background."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        try:
            self._refresh_task = asyncio.get_running_loop().create_task(self._refresh(delay))
        except RuntimeError:  # no event loop (tests, scripts)
            self._refresh_task = None

    async def _refresh(self, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            books = await self.books(include_disabled=True)
            if not books:
                return
            await asyncio.to_thread(self.index.forget_except, [b.name for b in books])
            for b in books:  # quick: a few requests per book
                try:
                    await self.survey(b)
                except httpx.HTTPError as e:
                    L.warning("survey of %s failed: %s", b.name, e)
            for b in books:  # slow: PDF text, one document at a time
                if b.kind == "documents":
                    await self._index_documents(b)
            self.index_state = {"state": "done", "done": self.index_state.get("done", 0), "total": self.index_state.get("total", 0), "current": ""}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            L.warning("library survey stopped: %s", e)
            self.index_state = {**self.index_state, "state": "error", "current": ""}

    async def survey(self, b: Book) -> dict:
        """Detect the book's kind and items, check its health, remember the result."""
        kind, docs, main, main_html = await self._detect(b)
        self._docs[b.name] = docs
        items = len(docs) if kind != "articles" else b.articles
        s = {"kind": kind, "items": items, "main": main}
        self._survey[b.name] = s
        self._apply_survey(b)
        s["health"] = await self._health(b, kind, docs, main, main_html)
        await asyncio.to_thread(self.index.set_zim_info, b.name, self._signature(b), kind, items, {"main": main, "health": s["health"]})
        return s

    async def _detect(self, b: Book) -> tuple[str, list[Doc], str, str]:
        kind, docs, main, html = await self._detect_kind(b)
        if kind in ("videos", "books") and not docs:
            text, links = _page_substance(html, b.name, main)
            if len(text) >= 200 or links >= 8:  # an older layout whose home page works without JavaScript
                return "articles", [], main, html
        return kind, docs, main, html

    async def _detect_kind(self, b: Book) -> tuple[str, list[Doc], str, str]:
        main = await self._main_path(b.name)
        page = await self._fetch(b.name, main, want_text=True) if main else None
        html = (page.text or "") if page and page.status == 200 else ""
        if page and page.final:
            main = page.final
        n = b.name.lower()
        if 'id="doc-list"' in html or "nautilus.js" in html:
            db = await self._fetch(b.name, "database.js", want_text=True, any_type=True)
            docs = nautilus_docs(db.text or "") if db and db.status == 200 else []
            await self._sizes(b.name, docs)
            return "documents", docs, main, html
        if 'id="video-items"' in html or (n.startswith("ted_") and not re.search(r"<h1|<article", html)):
            codes = ted_language_codes(html)
            prefer = sorted(codes, key=lambda c: (c not in ("en", "eng"), codes.index(c)))
            for path in [f"assets/data_{c}.js" for c in prefer] + ["assets/data.js"]:
                f = await self._fetch(b.name, path, want_text=True, any_type=True)
                docs = ted_docs(parse_js_data(f.text or "")) if f and f.status == 200 else []
                if docs:
                    return "videos", docs, main, html
            return "videos", [], main, html
        if "full_by_popularity.js" in html or 'id="books_table"' in html or (n.startswith("gutenberg_") and "datatable" in html.lower()):
            f = await self._fetch(b.name, "full_by_popularity.js", want_text=True, any_type=True)
            data = parse_js_data(f.text or "") if f and f.status == 200 else None
            docs = gutenberg_docs(data)
            if docs:  # cover pages lost their ".html" suffix in gutenberg2zim 3; check which one this ZIM has
                probe = await self._fetch(b.name, docs[0].path)
                if not probe or probe.status != 200:
                    docs = gutenberg_docs(data, html_suffix=True)
            return "books", docs, main, html
        return "articles", [], main, html

    async def _sizes(self, book: str, docs: list[Doc]) -> None:
        sem = asyncio.Semaphore(4)

        async def one(d: Doc):
            async with sem:
                f = await self._fetch(book, d.path)
                if f and f.status == 200:
                    d.size = f.length
                    d.mime = f.ctype or d.mime
                    d.kind = kind_of_mime(d.mime) if d.kind == "file" else d.kind

        await asyncio.gather(*(one(d) for d in docs), return_exceptions=True)

    async def _health(self, b: Book, kind: str, docs: list[Doc], main: str, html: str) -> dict:
        """Can this book be opened, and searched? Honest, plain-English answers for the card."""
        noun = KIND_NOUNS.get(kind, KIND_NOUNS["articles"])
        h: dict = {"checked_at": time.time(), "readable": False, "searchable": False, "note": ""}
        if kind == "documents":
            h["readable"] = bool(docs)
            pdfs = [d for d in docs if d.kind == "pdf"]
            n_docs, n_pages = await asyncio.to_thread(self.index.counts, b.name)
            h["searchable"] = n_docs > 0
            h["docs_indexed"], h["pages_indexed"] = n_docs, n_pages
            statuses = await asyncio.to_thread(self.index.doc_statuses, b.name)
            pending = [d for d in pdfs if d.path not in statuses]
            if not docs:
                h["note"] = "Its start page needs JavaScript, and Mimi couldn't find the document list inside it."
            elif pending:
                h["indexing"] = True
                h["note"] = f"Reading {len(pdfs)} {'document' if len(pdfs) == 1 else 'documents'} so Mimi can search them…"
            elif not h["searchable"]:
                h["note"] = "Mimi can open these documents, but found no text to search in them (they may be scans)."
            else:
                h["note"] = f"{n_pages:,} pages searchable"
        elif kind in ("videos", "books"):
            h["readable"] = bool(docs)
            h["searchable"] = await self._searchable(b, main)
            if not docs:
                h["note"] = f"Its start page needs JavaScript, and Mimi couldn't read its list of {noun[1]}."
        else:
            text, links = _page_substance(html, b.name, main)
            h["readable"] = len(text) >= 200 or links >= 8
            h["searchable"] = await self._searchable(b, main)
            if not h["readable"]:
                needs_js = bool(re.search(r"<script", html, re.I))
                h["note"] = ("Its start page is built by JavaScript, which Mimi's reader doesn't run." if needs_js
                             else "Its start page is empty.") + (" You can still find its articles by searching." if h["searchable"] else "")
            elif not h["searchable"]:
                h["note"] = "No search index: you can browse it, but Mimi can't search inside it."
        h["status"] = ("indexing" if h.get("indexing") else "ok" if h["readable"] and h["searchable"]
                       else "limited" if h["readable"] or h["searchable"] else "unreadable")
        return h

    async def _searchable(self, b: Book, main: str) -> bool:
        """Does full-text search find anything besides the home page?"""
        if "_ftindex:yes" in b.tags:
            return True
        words = [w for w in re.findall(r"[A-Za-z]{4,}", f"{b.title} {b.summary}") if w.lower() not in STOPWORDS] or ["the"]
        for w in words[:2]:
            try:
                hits = await self._search_group(w, [b], 3)
            except httpx.HTTPError:
                return False
            if any(h.path != main for h in hits):
                return True
        return False

    def health_of(self, b: Book) -> dict:
        s = self._survey.get(b.name)
        h = dict(s.get("health") or {}) if s else {}
        if not h:
            return {"status": "checking", "readable": None, "searchable": None, "note": i18n.localize("Checking this book…")}
        if b.kind == "documents" and h.get("indexing") and self.index_state.get("book") == b.name:
            h["note"] = f"Reading documents so Mimi can search them ({self.index_state['done']} of {self.index_state['total']})…"
        h["note"] = i18n.localize(h.get("note"))  # surveys are stored in English; read them in the asker's language
        return h

    async def collection(self, name: str) -> tuple[Book, list[Doc]] | None:
        """A collection book's items (documents, talks, books), with index status for PDFs."""
        b = await self.book(name)
        if not b:
            return None
        if b.name not in self._docs:
            try:
                await self.survey(b)
            except httpx.HTTPError as e:
                L.warning("survey of %s failed: %s", b.name, e)
        docs = self._docs.get(b.name, [])
        statuses = await asyncio.to_thread(self.index.doc_statuses, b.name)
        for d in docs:
            st = statuses.get(d.path)
            d.pages = int(st["pages"]) if st else 0
            d.indexed = bool(st and st["status"] == "ready" and st["pages"])
        return b, docs

    async def _doc_meta(self, book: str, path: str) -> Doc | None:
        if book not in self._docs:
            b = await self.book(book)
            if b and b.kind != "articles":
                try:
                    await self.survey(b)
                except httpx.HTTPError as e:
                    L.warning("survey of %s failed: %s", b.name, e)
        return next((d for d in self._docs.get(book, []) if d.path == path), None)

    # --- document text index ------------------------------------------------------
    async def _index_documents(self, b: Book) -> None:
        docs = self._docs.get(b.name, [])
        statuses = await asyncio.to_thread(self.index.doc_statuses, b.name)
        sig = self._signature(b)
        todo = [d for d in docs if (statuses.get(d.path) or {}).get("signature") != sig]
        if not todo:
            return
        L.info("indexing %d documents in %s", len(todo), b.name)
        self.index_state = {"state": "indexing", "book": b.name, "done": 0, "total": len(todo), "current": ""}
        # pypdf is pure Python: in a thread it would hold Core's GIL for minutes and slow every
        # request. A low-priority worker process keeps the app responsive; a thread is the fallback.
        pool: ProcessPoolExecutor | None = None
        try:
            if self.worker_process:  # "spawn" everywhere: what Windows does anyway, and safe in a threaded process
                pool = ProcessPoolExecutor(max_workers=1, initializer=lower_priority, mp_context=multiprocessing.get_context("spawn"))
        except (OSError, ValueError, NotImplementedError) as e:
            L.info("no worker process for PDF text (%s); using a thread", e)
        self._pool = pool
        try:
            await self._index_docs(b, todo, sig, pool)
        finally:
            if pool and self._pool is pool:
                self._pool = None
                pool.shutdown(wait=False, cancel_futures=True)
        s = self._survey.get(b.name)
        if s:
            s["health"] = await self._health(b, s["kind"], docs, s.get("main", ""), "")
            await asyncio.to_thread(self.index.set_zim_info, b.name, sig, s["kind"], s["items"], {"main": s.get("main", ""), "health": s["health"]})

    async def _index_docs(self, b: Book, todo: list[Doc], sig: str, pool: ProcessPoolExecutor | None) -> None:
        loop = asyncio.get_running_loop()
        for i, d in enumerate(todo):
            self.index_state.update(done=i, current=d.title)
            pages: list = []
            status, error = "meta", ""
            if d.kind == "pdf":
                try:
                    data = await self._download(b.name, d.path, MAX_PDF_BYTES)
                except httpx.HTTPError as e:  # kiwix-serve restarting: try again on the next pass
                    L.warning("couldn't fetch %s/%s: %s", b.name, d.path, e)
                    return
                if data is None:
                    status, error = "skipped", "too large or missing"
                else:
                    t0 = time.time()
                    try:
                        try:
                            if pool is None:
                                raise BrokenProcessPool("no worker process")
                            pages = await loop.run_in_executor(pool, pdf_pages, data)
                        except (BrokenProcessPool, OSError, RuntimeError) as e:  # no worker after all: do it here
                            if pool is not None:
                                L.info("PDF worker process failed (%s); using a thread", e)
                            pool = None
                            pages = await asyncio.to_thread(pdf_pages, data)
                        status = "ready" if pages else "empty"
                    except Exception as e:  # a broken PDF shouldn't stop the others
                        status, error = "error", str(e)[:200]
                    L.info("indexed %s (%d pages with text) in %.1fs", d.title, len(pages), time.time() - t0)
            await asyncio.to_thread(self.index.put_document, b.name, d, sig, pages, status, error)
        self.index_state.update(done=len(todo), current="")

    async def _download(self, book: str, path: str, max_bytes: int) -> bytes | None:
        url = f"{self.service.base}/content/{book}/{quote_path(path)}"
        async with self.http.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(connect=3, read=120, write=10, pool=5)) as r:
            if r.status_code != 200 or int(r.headers.get("content-length") or 0) > max_bytes:
                return None
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    return None
            return bytes(buf)

    # --- embeddings (optional) ------------------------------------------------------
    async def _http_embed(self, texts: list[str]) -> list[list[float]]:
        """bge-m3 via the embedding server, only if it is already running (never starts it)."""
        from .llm import EMBED_PORT

        r = await self.http.post(f"http://127.0.0.1:{EMBED_PORT}/v1/embeddings", json={"input": [t[:2000] or " " for t in texts], "model": "embed"},
                                 timeout=httpx.Timeout(connect=0.3, read=RERANK_TIMEOUT, write=1, pool=0.5))
        r.raise_for_status()
        if self.on_embed:
            self.on_embed()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]

    async def _embed(self, texts: list[str], timeout: float) -> list[list[float]] | None:
        if not texts or time.time() < self._embed_down_until:
            return None
        try:
            return await asyncio.wait_for(self.embedder(texts), timeout)
        except Exception as e:  # server down, busy or slow: rank without it
            L.debug("embedding skipped: %s", e)
            self._embed_down_until = time.time() + EMBED_RETRY_AFTER
            return None

    async def _embed_with_query(self, query: str, texts: list[str], timeout: float) -> tuple[list[float], list[list[float]]] | None:
        q = self._qvecs.get(query)
        vecs = await self._embed(texts if q else [query, *texts], timeout)
        if not vecs:
            return None
        if not q:
            q, vecs = vecs[0], vecs[1:]
            self._qvecs[query] = q
            while len(self._qvecs) > 64:
                self._qvecs.pop(next(iter(self._qvecs)))
        return q, vecs

    # --- search ---------------------------------------------------------------
    async def search(self, query: str, collections: list[str] | None = None, books: list[str] | None = None, limit: int = 5,
                     local: tuple[str, str] | None = None) -> list[Hit]:
        """Fused results from every chosen book: Xapian per language group, a title
        lookup and the document-page index, ranked by retrieval.rrf with intent
        priors, then (when embeddings are up) reranked semantically.

        ``local`` is (language, query): books in that language (Kiwix codes: "spa", "fra")
        are searched with that query instead, so Spanish books are searched in Spanish."""
        lang, local_q = local if local and local[1].strip() else ("", "")

        def q_for(language: str) -> str:
            return local_q if lang and language == lang else query

        all_books = await self.books()
        if books:
            chosen = [b for b in all_books if b.name in books or b.alias in books]
        elif collections:
            chosen = [b for b in all_books if b.collection in collections]
        else:
            chosen = [b for b in all_books if b.collection not in ("talks", "books", "courses", "dictionary")]
        if not chosen:
            return []
        # Xapian only knows a nautilus ZIM's home page; its text lives in our index.
        text_books = [b for b in chosen if b.kind != "documents"]
        doc_books = [b for b in chosen if b.kind == "documents"]
        by_lang: dict[str, list[Book]] = {}
        for b in text_books:
            by_lang.setdefault(b.language or "eng", []).append(b)
        per = max(limit, 8)
        local_books = [b for b in text_books if lang and b.language == lang]
        other_books = [b for b in text_books if b not in local_books]
        async def titles(q: str, books_: list[Book], language: str = "") -> list[tuple[str, Hit]]:
            return await self._resolve_redirects(await self._title_hits(q, books_, language))

        titled, local_titled, docs, *groups = await asyncio.gather(
            titles(query, other_books), titles(local_q, local_books, lang), self._doc_hits(query, doc_books, per),
            *(self._search_group(q_for(language), grp, per) for language, grp in by_lang.items()), return_exceptions=True)
        pairs = (titled if isinstance(titled, list) else []) + (local_titled if isinstance(local_titled, list) else [])
        # A title that is only a small part of the question ("Since", "Ratio", "Warm It Up" in a frostbite
        # question) is often just its words: it counts as the topic only when the full-text search found
        # that article too, or when it comes from a book on the question's subject ("Hypothermia" in
        # MDWiki for a medical question, which MDWiki's own full-text search didn't rank in its top 8).
        # Redirects were followed, so a hit is the article itself.
        found = {(h.book, h.path) for g in groups if isinstance(g, list) for h in g}
        intent = R.detect_intent(query)

        def tier(matched: str, h: Hit) -> int | None:
            if (h.book, h.path) in found:
                return 0  # full-text search agrees: first
            if _title_is_topic(matched, local_q if lang and h.language == lang else query) or R.prior(h.collection, intent) > 1.0:
                return 1
            return None

        tiers = [(t, h) for matched, h in pairs if (t := tier(matched, h)) is not None]
        # three, not two: a generic word can redirect to an article the full text also finds ("Temperature" →
        # Thermoregulation) and would otherwise crowd out the topic's own title. Three different titles, each
        # from every book that has it: the same "First aid" from three books would crowd out "Burn" in "burn
        # first aid", and keeping one copy would drop MDWiki's "Myocardial infarction" for Wikipedia's.
        ordered = [h for _, h in sorted(tiers, key=lambda x: x[0])]
        names = list(dict.fromkeys(h.title.lower() for h in ordered))[:3]
        titled = [h for h in ordered if h.title.lower() in names]
        index: dict[tuple, Hit] = {}

        def ranked(name: str, hits, weight: float) -> R.RankedList:
            items = []
            for h in hits if isinstance(hits, list) else []:
                key = (h.book, h.path, h.page)
                if key not in index or (h.snippet and not index[key].snippet):
                    index[key] = h
                items.append(R.Candidate(key, h.collection, h.book, f"{h.title}. {h.snippet}"))
            return R.RankedList(name, items, weight)

        lists = [ranked("title", titled, 2.0)]
        lists += R.split_by_book(ranked("docs", docs, 1.0))
        for i, g in enumerate(groups):
            lists += R.split_by_book(ranked(f"xapian{i}", g, 1.0))
        fused = R.rrf(lists, R.detect_intent(query))
        fused = R.cap_per_key(fused, lambda c: c.key[:2], 2)  # at most two pages of one PDF
        head = fused[:RERANK_CANDIDATES]
        if len(head) > 2:
            got = await self._embed_with_query(query, [c.text for c in head], RERANK_TIMEOUT)
            if got:
                head = R.semantic_rerank(head, got[0], got[1])
                fused = head + fused[RERANK_CANDIDATES:]
        out = []
        for c in fused[: limit * 2]:
            h = index[c.key]
            h.score = round(c.score, 4)
            out.append(h)
        return out

    async def _doc_hits(self, query: str, books: list[Book], limit: int) -> list[Hit]:
        if not books:
            return []
        terms = [t for t in R.tokens(query) if t not in STOPWORDS and len(t) > 1][:12]
        rows = await asyncio.to_thread(self.index.search, terms, [b.name for b in books], limit * 2)
        by_name = {b.name: b for b in books}
        hits = []
        for r in rows:
            b = by_name.get(r["zim"])
            if not b:
                continue
            page = int(r["page"] or 0)
            title = (r["title"] or r["path"]).strip()
            label = page_label(page, r["label"] or "") if page else ""
            hits.append(Hit(title=f"{title}, p. {label}" if page else title, path=r["path"], book=b.name, book_title=b.title, language=b.language,
                            collection=b.collection, snippet=re.sub(r"\s+", " ", r["snippet"] or "").strip()[:400], page=page, label=label))
        return hits

    async def _title_hits(self, query: str, books: list[Book], language: str = "") -> list[Hit]:
        """An article whose title *is* the topic ("Bee sting") beats full-text relevance.

        Look up runs of the query's words as titles in the largest few books, longest first
        (4 content words → 1, anywhere in the query, little words inside a run kept: "great wall
        of china"), and keep the suggestions whose title appears in the query: word for word
        ("Speed of light" in "what is the speed of light in a vacuum"), or without its little
        words when it has some ("Picadura de abeja" in "picadura abeja"). A title without little
        words must appear word for word, so "speed of light" doesn't find the "Speed light" flash.
        ``language`` (a Kiwix code) picks the little words when the books aren't English.
        One-word titles are checked against the full-text results in search().
        """
        stop = R.STOPWORDS_BY_LANGUAGE.get(language, STOPWORDS)
        raw = [w.lower() for w in re.findall(r"[^\W_][\w'’-]*", query)]
        content = [i for i, w in enumerate(raw) if w not in stop][:6]
        # Q&A titles are whole questions, almost never a topic's name
        top = sorted((b for b in books if b.collection != "qa"), key=lambda b: -b.articles)[:4]
        if not content or not top:
            return []
        qraw = " " + " ".join(raw) + " "
        qbare = " " + " ".join(w for w in raw if w not in stop) + " "
        # Every run at once, longest first: a generic title ("First aid") must not hide the topic's
        # own ("Nosebleed" in "how to stop a nosebleed first aid"); search() picks among them.
        terms: list[str] = []
        for n in range(min(4, len(content)), 0, -1):
            for s in range(len(content) - n + 1):
                term = " ".join(raw[content[s]:content[s + n - 1] + 1])
                if (n > 1 or len(term) >= 4) and term not in terms:  # "burn", not "cut"
                    terms.append(term)
        pairs = [(t, b) for t in terms for b in top]
        got = await asyncio.gather(*(self.suggest(t, b.name, 8) for t, b in pairs), return_exceptions=True)
        out: list[Hit] = []
        seen: set[tuple[str, str]] = set()
        for (_, b), res in zip(pairs, got):
            for s in res if isinstance(res, list) else []:
                t = (s.get("title") or "").strip()
                tw = re.findall(r"[^\W_][\w'’-]*", t.lower())
                bare = [w for w in tw if w not in stop]
                traw, tbare = " " + " ".join(tw) + " ", " " + " ".join(bare) + " "
                if not (t and s.get("path") and len(tbare.strip()) >= 4) or (b.name, tbare) in seen:
                    continue
                # without its little words only when they sit inside it ("Picadura de abeja", not "Childhood ME")
                inside = len(bare) < len(tw) and tw[0] not in stop and tw[-1] not in stop
                if traw in qraw or (inside and tbare in qbare):
                    seen.add((b.name, tbare))
                    out.append(Hit(title=t, path=s["path"], book=b.name, book_title=b.title, collection=b.collection, snippet="",
                                   score=2.0, language=b.language))
        # ten, not six: the big books' "Rice" and "Stand" for "what does RICE stand for in treating a sprained
        # ankle" filled six places before MDWiki's "Sprained" (→ Sprain); search() then drops most of them
        return out[:10]

    async def _resolve_redirects(self, hits: list[Hit]) -> list[tuple[str, Hit]]:
        """(title as matched, hit) with each hit pointing at the article its title redirects to.

        Titles from the lookup are often redirects ("Capital of Australia" → Canberra). Pointing them at
        the article lets them merge with its full-text hit, shows its real title and keeps one article
        from taking two of the few places in an answer's sources."""
        got = await asyncio.gather(*(self._fetch(h.book, h.path) for h in hits), return_exceptions=True)
        out: list[tuple[str, Hit]] = []
        seen: set[tuple[str, str]] = set()
        for h, f in zip(hits, got):
            matched = h.title
            if isinstance(f, Fetched) and f.status == 200 and f.final and f.final != h.path:
                h.path, h.title = f.final, f.final.rsplit("/", 1)[-1].replace("_", " ")
            if (h.book, h.path) not in seen:
                seen.add((h.book, h.path))
                out.append((matched, h))
        return out

    async def _search_group(self, query: str, group: list[Book], limit: int) -> list[Hit]:
        params = [("pattern", query), ("format", "xml"), ("pageLength", str(limit)), ("start", "0")] + [("books.name", b.name) for b in group]
        r = await self.http.get(f"{self.service.base}/search", params=params)
        if r.status_code != 200:
            return []
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            return []
        by_title = {b.title: b for b in group}
        mains = {b.name: b.main for b in group if b.kind != "articles" and b.main}
        hits: list[Hit] = []
        for i, item in enumerate(root.iter("item")):
            link = item.findtext("link") or ""
            m = re.match(r"^/content/([^/]+)/(.+)$", link)
            if not m:
                continue
            book_name, path = m.group(1), unquote(m.group(2))
            title = item.findtext("title") or ""
            # Index/listing pages (Stack Exchange tag pages, user pages) make poor sources.
            if re.match(r"^(questions/tagged/|tags/|users/|questions$)", path) or title.startswith(("Questions tagged", "Newest ")):
                continue
            if mains.get(book_name) == path:  # a JS-driven home page (TED, Gutenberg) has nothing to read
                continue
            book = next((b for b in group if b.name == book_name), None) or by_title.get(item.findtext("book/title") or "")
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item.findtext("description") or "")).strip()
            hits.append(
                Hit(
                    title=item.findtext("title") or path.replace("_", " "),
                    path=path,
                    book=book.name if book else book_name,
                    book_title=book.title if book else book_name,
                    collection=book.collection if book else collection_of(book_name),
                    snippet=snippet[:400],
                    words=int(re.sub(r"\D", "", item.findtext("wordCount") or "0") or 0),
                    score=1.0 / (1 + i),
                    language=book.language if book else "",
                )
            )
        return hits

    async def suggest(self, query: str, book: str, count: int = 8) -> list[dict]:
        r = await self.http.get(f"{self.service.base}/suggest", params={"content": book, "term": query, "count": count})
        if r.status_code != 200:
            return []
        try:
            data = r.json()
        except ValueError:
            return []
        return [{"title": d.get("value", ""), "path": d.get("path")} for d in data if d.get("kind") == "path"]

    # --- articles -------------------------------------------------------------
    async def _fetch(self, book: str, path: str, want_text: bool = False, any_type: bool = False) -> Fetched | None:
        """GET a ZIM entry, following redirects. The body is read only when it is
        HTML (or `any_type`) and `want_text`, so probing a 14 MB PDF costs nothing."""
        url = f"{self.service.base}/content/{book}/{quote_path(path)}"
        async with self.http.stream("GET", url, follow_redirects=True) as r:
            ctype = r.headers.get("content-type", "").split(";")[0].strip()
            final = unquote(str(r.url).split(f"/content/{book}/", 1)[-1]) if f"/content/{book}/" in str(r.url) else path
            f = Fetched(r.status_code, ctype, final, int(r.headers.get("content-length") or 0))
            if r.status_code == 200 and want_text and (any_type or ctype == "text/html"):
                await r.aread()
                f.text = r.text
            return f

    async def _main_path(self, book: str) -> str:
        r = await self.http.get(f"{self.service.base}/content/{book}", follow_redirects=False)
        loc = r.headers.get("location", "")
        return unquote(loc.split(f"/content/{book}/", 1)[-1]) if loc else ""

    async def raw(self, book: str, path: str) -> tuple[str, str] | None:
        """Fetch article HTML; returns (html, final_path) following redirects. None for non-HTML entries."""
        f = await self._fetch(book, path, want_text=True)
        if not f or f.status != 200 or f.text is None:
            return None
        return f.text, f.final

    async def passage(self, hit: Hit, query: str, max_chars: int) -> Passage | None:
        if hit.page or is_document_path(hit.path):
            return await self._doc_passage(hit, query, max_chars)
        got = await self.raw(hit.book, hit.path)
        if not got:
            return None
        html, path = got
        title, image, blocks = article_blocks(html, book=hit.book, path=path)
        if not blocks:
            title, text, image = extract_passage(html, query, max_chars, book=hit.book, path=path)
        else:
            scores = score_blocks(blocks, title, query)
            scores = await self._semantic_blend(query, [t for _, t in blocks], scores)
            text = select_blocks(blocks, scores, max_chars)
        return Passage(
            title=title or hit.title,
            book=hit.book,
            book_title=hit.book_title,
            collection=hit.collection,
            path=path,
            text=text,
            image=image,
            url=f"/library/read/{alias_of(hit.book)}/{path}",
        )

    async def _semantic_blend(self, query: str, texts: list[str], lexical: list[float]) -> list[float]:
        """Blend embedding similarity into the best few lexical candidates (others keep their lexical score)."""
        idx = [i for i in sorted(range(len(texts)), key=lambda i: -lexical[i]) if lexical[i] > 0][:PASSAGE_EMBED_CHUNKS]
        if len(idx) < 2:
            return lexical
        got = await self._embed_with_query(query, [texts[i][:1200] for i in idx], PASSAGE_EMBED_TIMEOUT)
        if not got:
            return lexical
        q, vecs = got
        blended = R.blend_passage_scores([lexical[i] for i in idx], [R.cosine(q, v) for v in vecs])
        top = max(lexical)
        out = list(lexical)
        for i, s in zip(idx, blended):
            out[i] = s * top + 1e-6  # back on the lexical scale, ahead of anything not considered
        return out

    async def _doc_passage(self, hit: Hit, query: str, max_chars: int) -> Passage | None:
        b = await self.book(hit.book)
        name = b.name if b else hit.book
        doc = await self._doc_meta(name, hit.path)
        doc_title = doc.title if doc else hit.title.split(", p. ")[0]
        page = hit.page
        terms = [t for t in R.tokens(query) if t not in STOPWORDS and len(t) > 1][:12]
        if not page:
            rows = [r for r in await asyncio.to_thread(self.index.search, terms, [name], 4, hit.path) if r["page"]]
            if rows:
                page = int(rows[0]["page"])
        alias = alias_of(name)
        url = f"/library/read/{alias}/{quote_path(hit.path)}"
        base = dict(book=name, book_title=b.title if b else hit.book_title, collection=b.collection if b else hit.collection, path=hit.path)
        if not page:  # no text for this document: offer what we know about it
            if not doc:
                return None
            about = " ".join(x for x in (f"By {doc.author}." if doc.author else "", doc.description) if x)
            return Passage(title=doc_title, text=about or doc_title, url=url, extra={"kind": doc.kind}, **base)
        # The cited page, plus the next one: a paragraph often runs over the page break.
        rows = [await asyncio.to_thread(self.index.page_text, name, hit.path, p) for p in (page, page + 1)]
        chunks: list[str] = []
        owner: list[int] = []
        labels: dict[int, str] = {}
        for p, r in zip((page, page + 1), rows):
            if r:
                labels[p] = page_label(p, r["label"] or "")
                for c in R.chunk_text(r["text"]):
                    chunks.append(c)
                    owner.append(p)
        if not chunks:
            return None
        raw = R.bm25_scores(chunks, R.query_terms(query))
        lexical = [s + (0.5 if owner[i] == page else 0.0) for i, s in enumerate(raw)]  # the cited page first
        scores = await self._semantic_blend(query, chunks, lexical)
        # The next page only contributes what is actually about the question.
        pool = [i for i in range(len(chunks)) if owner[i] == page or raw[i] > 0]
        chosen, total = [], 0
        for i in sorted(pool, key=lambda i: -scores[i]):
            if total >= max_chars:
                break
            chosen.append(i)
            total += len(chunks[i]) + 1
        text = "\n".join(chunks[i] for i in sorted(chosen))
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0] + " …"
        used = sorted({owner[i] for i in chosen})
        first = labels.get(used[0], str(used[0]))
        cite = f"p. {first}" if len(used) == 1 else f"pp. {first}–{labels.get(used[-1], str(used[-1]))}"
        return Passage(title=f"{doc_title}, {cite}", text=text, url=f"{url}#page={used[0]}",
                       extra={"kind": "pdf", "page": used[0], "label": first}, **base)

    async def reader(self, book: str, path: str) -> dict | None:
        b = await self.book(book)
        if b and b.name not in self._survey:  # opened before the background survey reached it
            try:
                await self.survey(b)
            except httpx.HTTPError as e:
                L.warning("survey of %s failed: %s", b.name, e)
        name = b.name if b else book
        alias, book_title = alias_of(name), b.title if b else name
        base = {"book": name, "alias": alias, "book_title": book_title, "html": "", "image": None, "toc": []}
        if b and b.kind != "articles" and path in ("", b.main):
            return {**base, "kind": "collection", "title": b.title, "path": path}
        f = await self._fetch(name, path, want_text=True)
        if not f or f.status != 200:
            return None
        if f.text is not None:
            return {"kind": "article", **render_reader(f.text, name, f.final, alias, book_title)}
        doc = await self._doc_meta(name, f.final) if b and b.kind != "articles" else None
        out = {**base, "kind": kind_of_mime(f.ctype), "path": f.final, "mime": f.ctype, "size": f.length,
               "title": doc.title if doc else f.final.rsplit("/", 1)[-1], "src": f"/kiwix/content/{name}/{quote_path(f.final)}",
               "author": doc.author if doc else "", "description": doc.description if doc else ""}
        if out["kind"] == "pdf":
            st = await asyncio.to_thread(self.index.doc_status, name, f.final)
            out["pages"] = int(st["pages"]) if st else 0
            out["indexed"] = bool(st and st["status"] == "ready" and st["pages"])
        return out

    async def image_bytes(self, book: str, src: str) -> tuple[bytes, str] | None:
        r = await self.http.get(f"{self.service.base}{src}")
        if r.status_code != 200:
            return None
        return r.content, r.headers.get("content-type", "image/jpeg")


# --------------------------------------------------------------------------- HTML → text
_DROP = [
    "script", "style", "noscript", "sup.reference", "span.mw-editsection", ".navbox", ".vertical-navbox", ".reflist",
    ".references", ".mw-references-wrap", ".hatnote", ".metadata", ".ambox", ".sidebar", "#toc", ".toc", ".mw-cite-backlink",
    ".noprint", ".printfooter", "#catlinks", ".catlinks", "#footer", ".navigation-not-searchable", "table.infobox",
    ".thumb", "figure", ".gallery", ".mw-empty-elt", "link", "meta", ".kiwix-footer", "header", "nav",
]


INTENT_SYNONYMS = {
    "treat": ("management", "treatment", "first aid", "therapy"),
    "cure": ("management", "treatment"),
    "symptom": ("signs", "presentation"),
    "cause": ("causes", "etiology", "risk factors"),
    "prevent": ("prevention",),
    "fix": ("repair", "replacement", "troubleshooting"),
    "histor": ("history", "background"),
}


def _clean(s: str) -> str:
    s = re.sub(r"\[\d+\]|\[citation needed\]|\[edit\]", "", s)
    return re.sub(r"\s+", " ", s).strip()


_NOT_CONTENT_IMG = re.compile(r"(logo|icon|favicon|sprite|badge|avatar|gravatar|button|spinner|flag_of|filler|blank|pixel)", re.I)


def lead_image(tree: HTMLParser, book: str, path: str) -> str | None:
    for sel in ("table.infobox img", "figure img", ".thumb img", ".mw-file-element", "article img", "img"):
        for img in tree.css(sel):
            src = img.attributes.get("src") or ""
            w = int(re.sub(r"\D", "", img.attributes.get("width") or "0") or 0)
            h = int(re.sub(r"\D", "", img.attributes.get("height") or "0") or 0)
            if not src or _scheme(src) or (w and w < 80) or (h and h < 60) or _NOT_CONTENT_IMG.search(src + " " + (img.attributes.get("alt") or "")):
                continue
            if src.lower().endswith(".svg") and not tree.css_first("table.infobox"):
                continue
            abs_src = urljoin(f"/content/{book}/{path}", src)
            return "/kiwix" + abs_src
    return None


def article_blocks(html: str, book: str = "", path: str = "") -> tuple[str, str | None, list[tuple[str, str]]]:
    """(title, lead image, [(kind, text)]) where kind is "h" (h2/h3 heading) or "p" (paragraph, list item…)."""
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    title = _clean(h1.text()) if h1 else _clean(tree.css_first("title").text() if tree.css_first("title") else "")
    image = lead_image(tree, book, path)
    for sel in _DROP:
        for n in tree.css(sel):
            n.decompose()
    root = tree.css_first(".mw-parser-output") or tree.css_first("#mw-content-text") or tree.body or tree.root
    blocks: list[tuple[str, str]] = []
    if root is not None:
        for n in root.traverse(include_text=False):
            tag = n.tag
            if tag in ("h2", "h3"):
                t = _clean(n.text())
                if t:
                    blocks.append(("h", t))
            elif tag in ("p", "li", "dd", "blockquote", "pre"):
                if n.parent is not None and n.parent.tag in ("li",):
                    continue
                t = _clean(n.text())
                if len(t) >= 40 or (tag == "li" and len(t) >= 12):
                    blocks.append(("p", t))
    # Keep paragraphs bite-sized so several relevant ones fit the budget.
    blocks = [(k, t if k == "h" or len(t) <= 520 else t[:520].rsplit(" ", 1)[0] + " …") for k, t in blocks]
    lead = next((i for i, (k, _) in enumerate(blocks) if k == "p"), None)
    if lead is not None and len(blocks[lead][1]) > 480:
        blocks[lead] = ("p", blocks[lead][1][:480].rsplit(" ", 1)[0] + " …")
    return title, image, blocks


def score_blocks(blocks: list[tuple[str, str]], title: str, query: str) -> list[float]:
    """Lexical relevance of each block (0 for headings): BM25 over the article's own
    paragraphs, plus credit when the section heading matches the query or the
    question's intent ("treat" → a Management section)."""
    terms = R.query_terms(query)
    raw_terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in STOPWORDS]
    boost_sections = {syn for stem, syns in INTENT_SYNONYMS.items() if any(t.startswith(stem[:4]) for t in raw_terms) for syn in syns}
    # Words from the article title appear everywhere; they carry little signal.
    title_stems = {R.stem(w) for w in R.tokens(title)}
    weights = {t: (0.25 if t in title_stems else 1.0) for t in terms}
    paras = [i for i, (k, _) in enumerate(blocks) if k == "p"]
    bm = R.bm25_scores([blocks[i][1] for i in paras], terms, weights=weights)
    lexical = dict(zip(paras, bm))
    out: list[float] = []
    section = ""
    for i, (k, t) in enumerate(blocks):
        if k == "h":
            section = t.lower()
            out.append(0.0)
            continue
        sec_terms = {R.stem(w) for w in R.tokens(section)}
        s = lexical.get(i, 0.0)
        s += 1.0 * sum(weights.get(t, 1.0) for t in terms if t in sec_terms)
        s += 1.5 if any(b in section for b in boost_sections) else 0.0
        out.append(s)
    return out


def select_blocks(blocks: list[tuple[str, str]], scores: list[float], max_chars: int) -> str:
    """The lead paragraph plus the best-scoring ones, in article order, under their headings."""
    lead = [i for i, (k, _) in enumerate(blocks) if k == "p"][:1]
    ranked = sorted((i for i, (k, _) in enumerate(blocks) if k == "p" and scores[i] > 0), key=lambda i: (-scores[i], i))
    chosen = set(lead)
    total = sum(len(blocks[i][1]) for i in chosen)
    for i in ranked:
        if total >= max_chars:
            break
        if i not in chosen:
            chosen.add(i)
            total += len(blocks[i][1])
    out: list[str] = []
    last_h = None
    for i in sorted(chosen):
        if i not in lead:  # attach the nearest section heading for context
            for j in range(i, -1, -1):
                if blocks[j][0] == "h":
                    if blocks[j][1] != last_h:
                        out.append(f"## {blocks[j][1]}")
                        last_h = blocks[j][1]
                    break
        out.append(blocks[i][1])
    text = "\n".join(out)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    return text


def extract_passage(html: str, query: str, max_chars: int, book: str = "", path: str = "") -> tuple[str, str, str | None]:
    title, image, blocks = article_blocks(html, book, path)
    if not blocks:
        tree = HTMLParser(html)
        for sel in ("script", "style", "noscript"):
            for n in tree.css(sel):
                n.decompose()
        root = tree.body or tree.root
        text = _clean(root.text() if root is not None else "")
        return title, text[:max_chars], image
    return title, select_blocks(blocks, score_blocks(blocks, title, query), max_chars), image


def _page_substance(html: str, book: str, path: str) -> tuple[str, int]:
    """(visible text, number of internal links) of a page as Mimi's reader would show it."""
    if not html:
        return "", 0
    r = render_reader(html, book, path, alias_of(book), "")
    tree = HTMLParser(r["html"] or "<p></p>")
    text = _clean((tree.body or tree.root).text() if (tree.body or tree.root) is not None else "")
    return text, len(tree.css("a[data-internal]"))


# --------------------------------------------------------------------------- reader
_READER_DROP = [
    "script", "style", "noscript", "link", "meta", ".mw-editsection", ".navbox", ".vertical-navbox", ".printfooter",
    "#catlinks", ".catlinks", ".noprint", ".mw-cite-backlink", "#toc", ".toc", ".kiwix-footer", "header", "nav", "#mw-navigation",
    ".mw-jump-link", ".mw-indicators", ".ambox", ".navigation-not-searchable",
    # Active content and anything that can navigate or load a page: never rendered.
    "iframe", "frame", "frameset", "object", "embed", "applet", "base", "portal", "form", "template",
]
_SAFE_ATTRS = {"href", "src", "alt", "title", "colspan", "rowspan", "width", "height", "class", "id", "srcset", "controls", "poster", "type", "lang", "dir",
               "kind", "srclang", "label", "start", "reversed", "datetime"}
_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.I)
_URL_JUNK = re.compile(r"[\x00-\x20\x7f]+")  # browsers ignore tabs/newlines inside a URL ("java\tscript:")


def _scheme(url: str) -> str:
    """The URL's scheme, lower-case, as a browser would parse it ('' for relative URLs)."""
    m = _SCHEME.match(_URL_JUNK.sub("", url))
    return m.group(1).lower() if m else ""


def _drop_attr(n: Node, name: str) -> None:
    """Remove every attribute called `name` (namespaced duplicates included)."""
    for _ in range(8):
        if name not in n.attributes:
            return
        try:
            del n.attrs[name]
        except KeyError:
            return


def render_reader(html: str, book: str, path: str, alias: str, book_title: str) -> dict:
    """Clean, script-free article HTML for the reader (rendered with {@html} in the UI).

    Links are rewritten to the in-app reader; http(s)/mailto links become inert
    "external" markers; every other URL scheme (javascript:, vbscript:, data:,
    file:…) is removed, except data: images in <img>.
    """
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    tnode = tree.css_first("title")
    title = _clean(h1.text()) if h1 else (_clean(tnode.text()) if tnode and _clean(tnode.text()) else path.replace("_", " "))
    image = lead_image(tree, book, path)
    for sel in _READER_DROP:
        for n in tree.css(sel):
            n.decompose()
    root = tree.css_first(".mw-parser-output") or tree.css_first("#mw-content-text") or tree.css_first("main") or tree.body
    base = f"/content/{book}/{path}"
    toc = []
    if root is not None:
        for n in root.traverse(include_text=False):
            # strip event handlers / inline styles / unknown attributes
            for attr in list(n.attributes.keys()):
                if attr not in _SAFE_ATTRS or attr.startswith("on"):
                    _drop_attr(n, attr)
            if n.tag == "a":
                href = (n.attributes.get("href") or "").strip()
                scheme = _scheme(href)
                _drop_attr(n, "href")  # all of them: an SVG <a> can carry href and xlink:href under one name
                if scheme in ("http", "https", "mailto") or href.startswith("//"):
                    n.attrs["data-external"] = "1"
                    n.attrs["href"] = "#"
                elif scheme:  # javascript:, vbscript:, data:, file:… — never a live link
                    pass
                elif href.startswith("#"):
                    n.attrs["href"] = href
                elif href:
                    target = urljoin(base, href)
                    m = re.match(r"^/content/([^/]+)/(.+)$", target.split("#")[0])
                    if m:
                        frag = ("#" + target.split("#", 1)[1]) if "#" in target else ""
                        n.attrs["href"] = f"/library/read/{alias_of(m.group(1))}/{m.group(2)}{frag}"
                        n.attrs["data-internal"] = "1"
                    else:
                        n.attrs["href"] = href
            elif n.tag in ("img", "source", "video", "audio", "track"):
                for attr in ("src", "poster"):
                    v = (n.attributes.get(attr) or "").strip()
                    if not v:
                        continue
                    scheme = _scheme(v)
                    _drop_attr(n, attr)
                    if scheme == "data" and n.tag == "img" and re.match(r"data:image/", _URL_JUNK.sub("", v), re.I):
                        n.attrs[attr] = v  # inline pictures are fine in an <img>
                    elif not scheme and not v.startswith("//"):  # remote, data:, javascript:… — nothing loads from outside the ZIM
                        n.attrs[attr] = "/kiwix" + urljoin(base, v)
                _drop_attr(n, "srcset")
                if n.tag == "img":
                    n.attrs["loading"] = "lazy"
            else:
                # Any other element carrying a URL (<area href>, SVG/MathML links…): relative or nothing.
                for attr in ("href", "src"):
                    v = n.attributes.get(attr)
                    if v is not None and (_scheme(v) or v.strip().startswith("//")):
                        _drop_attr(n, attr)
                if n.tag in ("h2", "h3"):
                    t = _clean(n.text())
                    if t:
                        anchor = n.attributes.get("id") or re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
                        n.attrs["id"] = anchor
                        if n.tag == "h2":
                            toc.append({"id": anchor, "title": t})
        body = root.html or ""
    else:
        body = ""
    return {
        "title": title,
        "book": book,
        "alias": alias,
        "book_title": book_title,
        "path": path,
        "html": body,
        "image": image,
        "toc": toc[:40],
    }


def book_dict(b: Book) -> dict:
    d = asdict(b)
    d["collection_label"] = COLLECTION_LABELS.get(b.collection, "Other")
    one, many = KIND_NOUNS.get(b.kind, KIND_NOUNS["articles"])
    if b.kind == "articles" and b.collection == "talks":
        one, many = "talk", "talks"
    d["item_noun"] = one if b.items == 1 else many
    return d


def hit_dict(h: Hit) -> dict:
    d = asdict(h)
    if h.page or is_document_path(h.path):
        d["url"] = f"/library/read/{alias_of(h.book)}/{quote_path(h.path)}" + (f"#page={h.page}" if h.page else "")
    else:
        d["url"] = f"/library/read/{alias_of(h.book)}/{h.path}"
    return d


def doc_dict(b: Book, d: Doc) -> dict:
    out = d.to_dict()
    out["url"] = f"/library/read/{b.alias}/{quote_path(d.path)}"
    out["src"] = f"/kiwix/content/{b.name}/{quote_path(d.path)}"
    out["thumb"] = f"/kiwix/content/{b.name}/{quote_path(d.thumb)}" if d.thumb else ""
    return out
