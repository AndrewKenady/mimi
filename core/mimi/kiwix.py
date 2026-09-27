"""Offline reference library: runs kiwix-serve over the ZIM collections and
turns its search/content APIs into LLM-ready passages and a clean reader view.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import httpx
from selectolax.parser import HTMLParser, Node

from . import log
from .events import EventBus
from .paths import Paths
from .procs import ManagedProcess
from .settings import SettingsStore

L = log.get("kiwix")
PORT = int(os.environ.get("MIMI_KIWIX_PORT", "7620"))
NS = {"a": "http://www.w3.org/2005/Atom"}

# Collection = a friendly grouping used by the UI and by the search tool.
COLLECTIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("medicine", "Medicine", ("mdwiki", "zimgit-medicine", "wikipedia_en_medicine", "wikem")),
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
STOPWORDS = set(
    "a an and are as at be by can do does for from how i if in into is it its me my of on or should the this to was what when where which who why will with you your".split()
)


def collection_of(name: str) -> str:
    n = name.lower()
    for key, _, pats in COLLECTIONS:
        if any(p in n for p in pats):
            return key
    return "other"


def alias_of(name: str) -> str:
    return re.sub(r"_\d{4}-\d{2}$", "", name)


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
    articles: int
    media: int
    collection: str
    icon: str | None
    file: str = ""
    size: int = 0
    pictures: bool = True
    videos: bool = False


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


# --------------------------------------------------------------------------- service
class KiwixService:
    """Owns the kiwix-serve process and restarts it when the ZIM set changes."""

    def __init__(self, paths: Paths, settings: SettingsStore, events: EventBus):
        self.paths = paths
        self.settings = settings
        self.events = events
        self.proc: ManagedProcess | None = None
        self.files: list[Path] = []
        self._task: asyncio.Task | None = None
        self.started_at = 0.0

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{PORT}"

    def zim_files(self) -> list[Path]:
        dirs = [self.paths.zim] + [Path(d) for d in self.settings.device("knowledge").extra_zim_dirs]
        files: list[Path] = []
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
                files.append(f)
        # If a full edition exists, hide small dev editions of the same family.
        names = [f.name for f in files]
        if any(n.startswith("wikipedia_en_all") for n in names):
            files = [f for f in files if not re.match(r"wikipedia_en_(100|top)", f.name)]
        return files

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
        args = [str(exe), "--address", "127.0.0.1", "--port", str(PORT), "--threads", "4", "-n", "-m", "-b", "-k", "-z",
                "--attachToProcess", str(os.getpid()), *[str(f) for f in self.files]]
        self.proc = ManagedProcess("kiwix-serve", args, cwd=self.paths.root, log_path=self.paths.logs / "kiwix.log")
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
        if self.proc:
            await asyncio.to_thread(self.proc.stop)
            self.proc = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    def alive(self) -> bool:
        return bool(self.proc and self.proc.alive())

    def watch(self, client: "KiwixClient") -> None:
        async def loop():
            while True:
                await asyncio.sleep(30)
                try:
                    current = self.zim_files()
                    if [f.name for f in current] != [f.name for f in self.files] or (self.files and not self.alive()):
                        L.info("ZIM set changed (%d → %d files); restarting kiwix-serve", len(self.files), len(current))
                        await self.restart()
                        client.invalidate()
                except Exception as e:  # keep watching no matter what
                    L.warning("kiwix watcher: %s", e)

        self._task = asyncio.create_task(loop())


# --------------------------------------------------------------------------- client
class KiwixClient:
    def __init__(self, service: KiwixService, settings: SettingsStore):
        self.service = service
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(connect=3, read=30, write=10, pool=5))
        self._books: list[Book] | None = None
        self._books_at = 0.0

    def invalidate(self) -> None:
        self._books = None

    async def books(self, include_disabled: bool = False) -> list[Book]:
        if self._books is None or time.time() - self._books_at > 600:
            self._books = await self._fetch_books()
            self._books_at = time.time()
        if include_disabled:
            return list(self._books)
        disabled = set(self.settings.device("knowledge").disabled_books)
        return [b for b in self._books if b.name not in disabled and b.alias not in disabled]

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

    # --- search ---------------------------------------------------------------
    async def search(self, query: str, collections: list[str] | None = None, books: list[str] | None = None, limit: int = 5) -> list[Hit]:
        all_books = await self.books()
        if books:
            chosen = [b for b in all_books if b.name in books or b.alias in books]
        elif collections:
            chosen = [b for b in all_books if b.collection in collections]
        else:
            chosen = [b for b in all_books if b.collection not in ("talks", "books", "courses", "dictionary")]
        if not chosen:
            return []
        by_lang: dict[str, list[Book]] = {}
        for b in chosen:
            by_lang.setdefault(b.language or "eng", []).append(b)
        results = await asyncio.gather(*(self._search_group(query, grp, limit) for grp in by_lang.values()), return_exceptions=True)
        hits: list[Hit] = []
        for res in results:
            if isinstance(res, list):
                hits.extend(res)
        return hits[: limit * 2]

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
    async def raw(self, book: str, path: str) -> tuple[str, str] | None:
        """Fetch article HTML; returns (html, final_path) following redirects."""
        url = f"{self.service.base}/content/{book}/{quote(path, safe='/:()%,_-.~')}"
        r = await self.http.get(url, follow_redirects=True)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            return None
        final = str(r.url).split(f"/content/{book}/", 1)[-1]
        return r.text, unquote(final)

    async def passage(self, hit: Hit, query: str, max_chars: int) -> Passage | None:
        got = await self.raw(hit.book, hit.path)
        if not got:
            return None
        html, path = got
        title, text, image = extract_passage(html, query, max_chars, book=hit.book, path=path)
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

    async def reader(self, book: str, path: str) -> dict | None:
        b = await self.book(book)
        name = b.name if b else book
        got = await self.raw(name, path)
        if not got:
            return None
        html, final = got
        return render_reader(html, name, final, alias_of(name), b.title if b else name)

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


def _terms(q: str) -> list[str]:
    """Query terms reduced to crude stems (first 5 letters) for tolerant matching."""
    toks = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if t not in STOPWORDS and len(t) > 1]
    return [t[:5] if len(t) > 5 else t for t in toks]


def _hits(text: str, stems: list[str], weights: dict[str, float] | None = None) -> float:
    words = re.findall(r"[a-z0-9]+", text.lower())
    w = weights or {}
    return sum(w.get(s, 1.0) for word in words for s in stems if word.startswith(s))


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
            if not src or src.startswith("data:") or (w and w < 80) or (h and h < 60) or _NOT_CONTENT_IMG.search(src + " " + (img.attributes.get("alt") or "")):
                continue
            if src.lower().endswith(".svg") and not tree.css_first("table.infobox"):
                continue
            abs_src = urljoin(f"/content/{book}/{path}", src)
            return "/kiwix" + abs_src
    return None


def extract_passage(html: str, query: str, max_chars: int, book: str = "", path: str = "") -> tuple[str, str, str | None]:
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    title = _clean(h1.text()) if h1 else _clean((tree.css_first("title").text() if tree.css_first("title") else ""))
    image = lead_image(tree, book, path)
    for sel in _DROP:
        for n in tree.css(sel):
            n.decompose()
    root = tree.css_first(".mw-parser-output") or tree.css_first("#mw-content-text") or tree.body or tree.root
    blocks: list[tuple[str, str]] = []  # (kind, text)
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
    if not blocks:
        text = _clean(root.text() if root is not None else tree.text())
        return title, text[:max_chars], image
    terms = _terms(query)
    boost_sections = {syn for stem, syns in INTENT_SYNONYMS.items() if any(t.startswith(stem[:4]) for t in terms) for syn in syns}
    # Words from the article title appear everywhere; they carry little signal.
    title_words = set(re.findall(r"[a-z0-9]+", title.lower()))
    weights = {t: (0.25 if any(w.startswith(t) for w in title_words) else 1.0) for t in terms}
    # Keep paragraphs bite-sized so several relevant ones fit the budget.
    blocks = [(k, t if k == "h" or len(t) <= 520 else t[:520].rsplit(" ", 1)[0] + " …") for k, t in blocks]
    lead = [i for i, (k, _) in enumerate(blocks) if k == "p"][:1]
    if lead and len(blocks[lead[0]][1]) > 480:
        blocks[lead[0]] = ("p", blocks[lead[0]][1][:480].rsplit(" ", 1)[0] + " …")
    scored = []
    section = ""
    for i, (k, t) in enumerate(blocks):
        if k == "h":
            section = t.lower()
            continue
        s = _hits(t, terms, weights) + 3 * _hits(section, terms, weights) + (4 if any(b in section for b in boost_sections) else 0)
        if s:
            scored.append((s, -i, i))
    scored.sort(reverse=True)
    scored = [(s, i) for s, _, i in scored]
    chosen = set(lead)
    total = sum(len(blocks[i][1]) for i in chosen)
    for s, i in scored:
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
    return title, text, image


# --------------------------------------------------------------------------- reader
_READER_DROP = [
    "script", "style", "noscript", "link", "meta", ".mw-editsection", ".navbox", ".vertical-navbox", ".printfooter",
    "#catlinks", ".catlinks", ".noprint", ".mw-cite-backlink", "#toc", ".toc", ".kiwix-footer", "header", "nav", "#mw-navigation",
    ".mw-jump-link", ".mw-indicators", ".ambox", ".navigation-not-searchable",
]
_SAFE_ATTRS = {"href", "src", "alt", "title", "colspan", "rowspan", "width", "height", "class", "id", "srcset", "controls", "poster", "type", "lang", "dir"}


def render_reader(html: str, book: str, path: str, alias: str, book_title: str) -> dict:
    tree = HTMLParser(html)
    h1 = tree.css_first("h1")
    title = _clean(h1.text()) if h1 else path.replace("_", " ")
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
                    try:
                        del n.attrs[attr]
                    except Exception:
                        pass
            if n.tag == "a":
                href = n.attributes.get("href") or ""
                if href.startswith(("http://", "https://", "//", "mailto:")):
                    n.attrs["data-external"] = "1"
                    n.attrs["href"] = "#"
                elif href.startswith("#"):
                    pass
                elif href:
                    target = urljoin(base, href)
                    m = re.match(r"^/content/([^/]+)/(.+)$", target.split("#")[0])
                    if m:
                        frag = ("#" + target.split("#", 1)[1]) if "#" in target else ""
                        n.attrs["href"] = f"/library/read/{alias_of(m.group(1))}/{m.group(2)}{frag}"
                        n.attrs["data-internal"] = "1"
            elif n.tag in ("img", "source", "video", "audio", "track"):
                for attr in ("src", "poster"):
                    v = n.attributes.get(attr)
                    if v and not v.startswith("data:"):
                        n.attrs[attr] = "/kiwix" + urljoin(base, v)
                if n.attributes.get("srcset"):
                    del n.attrs["srcset"]
                if n.tag == "img":
                    n.attrs["loading"] = "lazy"
            elif n.tag in ("h2", "h3"):
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
    return d


def hit_dict(h: Hit) -> dict:
    d = asdict(h)
    d["url"] = f"/library/read/{alias_of(h.book)}/{h.path}"
    return d
