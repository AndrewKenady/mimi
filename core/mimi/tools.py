"""Tools the model can call during a turn.

Each tool declares an OpenAI-style JSON schema, a human label for the activity
trail, and an availability check (e.g. `remember` disappears when memory is
off). Results carry numbered sources that the UI renders as citation chips.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import io
import json
import math
import operator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import log
from .auth import Ctx

L = log.get("tools")

COLLECTION_ENUM = ["auto", "encyclopedia", "medicine", "repair", "travel", "survival", "dictionary", "qa", "books", "talks"]
COLLECTION_NAMES = {
    "auto": "the library", "encyclopedia": "Wikipedia", "medicine": "WikiMed", "repair": "iFixit", "travel": "Wikivoyage",
    "survival": "survival guides", "dictionary": "the dictionary", "qa": "Stack Exchange", "books": "the book shelf", "talks": "TED talks",
}


@dataclass
class ToolResult:
    text: str
    label: str
    summary: str = ""
    sources: list[dict] = field(default_factory=list)
    images: list[str] = field(default_factory=list)  # data: URIs shown to the (vision) model
    data: dict = field(default_factory=dict)          # extra payload for the UI
    ok: bool = True


@dataclass
class TurnState:
    ctx: Ctx
    chat_id: str
    message_id: str
    query: str
    mode: dict
    vision: bool
    temporary: bool = False
    sources: list[dict] = field(default_factory=list)
    memory_events: list[dict] = field(default_factory=list)

    def add_source(self, src: dict) -> int:
        key = (src.get("type"), src.get("book") or src.get("doc_id"), src.get("path") or src.get("chunk") or src.get("title"))
        for s in self.sources:
            if (s.get("type"), s.get("book") or s.get("doc_id"), s.get("path") or s.get("chunk") or s.get("title")) == key:
                return s["n"]
        src["n"] = len(self.sources) + 1
        self.sources.append(src)
        return src["n"]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict, TurnState, Any], Awaitable[ToolResult]]
    available: Callable[[TurnState, Any], bool] = lambda st, svc: True

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


# --------------------------------------------------------------------------- helpers
def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


def _dedupe_hits(hits: list) -> list:
    seen, out = set(), []
    for h in hits:
        key = h.title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def _image_to_data_uri(data: bytes, max_side: int = 768) -> str | None:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        L.warning("image conversion failed: %s", e)
        return None


async def _find_article(svc, title: str, collection: str | None, st: TurnState):
    collections = None if not collection or collection == "auto" else [collection]
    books = await svc.kiwix.books()
    if collections:
        books = [b for b in books if b.collection in collections] or books
    else:
        pref = st.mode.get("collections") or []
        books = sorted(books, key=lambda b: (b.collection not in pref, b.collection != "encyclopedia"))
    for b in books[:6]:
        for s in await svc.kiwix.suggest(title, b.name, count=3):
            if s.get("path") and s["title"].strip().lower() == title.strip().lower():
                return b, s["path"]
    hits = await svc.kiwix.search(title, collections=collections, limit=3)
    if hits:
        h = hits[0]
        return await svc.kiwix.book(h.book), h.path
    return None, None


# --------------------------------------------------------------------------- library
async def search_library(args: dict, st: TurnState, svc) -> ToolResult:
    q = str(args.get("query") or st.query).strip()[:200]
    coll = args.get("collection") or "auto"
    if coll not in COLLECTION_ENUM:
        coll = "auto"
    ks = svc.settings.device("knowledge")
    collections = (st.mode.get("collections") or None) if coll == "auto" else [coll]
    hits = await svc.kiwix.search(q, collections=collections, limit=ks.articles_per_search + 2)
    if not hits and coll != "auto":
        hits = await svc.kiwix.search(q, collections=None, limit=ks.articles_per_search + 2)
    top = _dedupe_hits(hits)[: ks.articles_per_search]
    passages = await asyncio.gather(*(svc.kiwix.passage(h, q, ks.snippet_chars) for h in top), return_exceptions=True)
    blocks, sources = [], []
    for p in passages:
        if not p or isinstance(p, Exception):
            continue
        src = {
            "type": "library", "title": p.title, "book": p.book, "book_title": p.book_title, "collection": p.collection,
            "path": p.path, "url": p.url, "image": p.image, "snippet": p.text[:240],
        }
        n = st.add_source(src)
        sources.append(src)
        blocks.append(f"[{n}] {p.title} — {p.book_title}\n{p.text}")
    where = COLLECTION_NAMES.get(coll, "the library")
    if not blocks:
        return ToolResult(f"No results in the offline library for “{q}”. Try different words, or answer from general knowledge and say so.",
                          label=f"Searched {where} for “{q}”", summary="No results", ok=False)
    text = "\n\n".join(blocks) + "\n\nCite these as [n]."
    return ToolResult(text, label=f"Searched {where} for “{q}”", summary=f"Read {len(sources)} article{'s' if len(sources) != 1 else ''}", sources=sources)


async def read_article(args: dict, st: TurnState, svc) -> ToolResult:
    title = str(args.get("title") or "").strip()
    if not title:
        return ToolResult("Please give an article title.", label="Opened an article", ok=False)
    book, path = await _find_article(svc, title, args.get("collection"), st)
    if not book or not path:
        return ToolResult(f"No article titled “{title}” was found.", label=f"Looked for “{title}”", summary="Not found", ok=False)
    from .kiwix import Hit

    p = await svc.kiwix.passage(Hit(title=title, path=path, book=book.name, book_title=book.title, collection=book.collection, snippet=""), st.query, 3200)
    if not p:
        return ToolResult(f"Couldn't open “{title}”.", label=f"Opened “{title}”", ok=False)
    src = {"type": "library", "title": p.title, "book": p.book, "book_title": p.book_title, "collection": p.collection,
           "path": p.path, "url": p.url, "image": p.image, "snippet": p.text[:240]}
    n = st.add_source(src)
    return ToolResult(f"[{n}] {p.title} — {p.book_title}\n{p.text}", label=f"Read “{p.title}”", summary=p.book_title, sources=[src])


async def show_reference_image(args: dict, st: TurnState, svc) -> ToolResult:
    title = str(args.get("title") or "").strip()
    book, path = await _find_article(svc, title, args.get("collection"), st)
    if not book or not path:
        return ToolResult(f"No reference article for “{title}”.", label=f"Looked for a picture of “{title}”", ok=False)
    got = await svc.kiwix.raw(book.name, path)
    if not got:
        return ToolResult("Couldn't open the article.", label=f"Looked for a picture of “{title}”", ok=False)
    from selectolax.parser import HTMLParser

    from .kiwix import alias_of, lead_image

    html, final = got
    img = lead_image(HTMLParser(html), book.name, final)
    if not img:
        return ToolResult(f"“{title}” has no picture.", label=f"Looked for a picture of “{title}”", ok=False)
    fetched = await svc.kiwix.image_bytes(book.name, img[len("/kiwix"):])
    uri = _image_to_data_uri(fetched[0]) if fetched else None
    if not uri:
        return ToolResult("Couldn't load the picture.", label=f"Looked for a picture of “{title}”", ok=False)
    src = {"type": "library", "title": title, "book": book.name, "book_title": book.title, "collection": book.collection,
           "path": final, "url": f"/library/read/{alias_of(book.name)}/{final}", "image": img, "snippet": "Reference image"}
    n = st.add_source(src)
    return ToolResult(f"The reference image from [{n}] {title} ({book.title}) is attached below for you to look at.",
                      label=f"Looked at the picture of “{title}”", summary=book.title, sources=[src], images=[uri])


# --------------------------------------------------------------------------- personal
async def search_my_files(args: dict, st: TurnState, svc) -> ToolResult:
    q = str(args.get("query") or st.query).strip()
    results = await svc.docs.search(st.ctx.id, q, k=4)
    if not results:
        return ToolResult(f"Nothing in the user's files matches “{q}”.", label=f"Searched your files for “{q}”", summary="No matches", ok=False)
    blocks, sources = [], []
    for r in results:
        src = {"type": "note" if r["kind"] == "note" else "file", "title": r["title"], "doc_id": r["doc_id"], "chunk": r["chunk_id"],
               "url": r["url"], "snippet": r["text"][:240]}
        n = st.add_source(src)
        sources.append(src)
        blocks.append(f"[{n}] {r['title']}\n{r['text']}")
    return ToolResult("\n\n".join(blocks), label=f"Searched your files for “{q}”", summary=f"{len(sources)} match{'es' if len(sources) != 1 else ''}", sources=sources)


async def remember(args: dict, st: TurnState, svc) -> ToolResult:
    fact = str(args.get("fact") or "").strip()
    if not fact:
        return ToolResult("Nothing to remember.", label="Memory", ok=False)
    status, mem = await svc.memory.remember(st.ctx, fact, str(args.get("category") or "other"), st.chat_id, st.message_id)
    if status == "off":
        return ToolResult("Memory is turned off for this user; tell them you can't save it (they can enable memory in Settings).", label="Memory is off", ok=False)
    st.memory_events.append({"status": status, "memory": mem})
    if status == "saved":
        return ToolResult("Saved to memory.", label="Remembered", summary=fact[:80], data={"memory": mem})
    if status == "exists":
        return ToolResult("Already remembered.", label="Already remembered", summary=fact[:80], data={"memory": mem})
    return ToolResult("Suggested to the user for approval (they'll confirm it). Don't mention memory mechanics unless asked.",
                      label="Suggested a memory", summary=fact[:80], data={"memory": mem})


# --------------------------------------------------------------------------- location
async def where_am_i(args: dict, st: TurnState, svc) -> ToolResult:
    info = svc.location.describe()
    if not info:
        return ToolResult("The current location is unknown (no GPS fix and no location set). Ask the user where they are, or suggest setting it on the Map.",
                          label="Checked location", summary="Unknown", ok=False)
    return ToolResult(json.dumps(info, ensure_ascii=False), label="Checked location", summary=info.get("description", ""), data={"location": info})


async def nearby_places(args: dict, st: TurnState, svc) -> ToolResult:
    loc = svc.location.current()
    if not loc:
        return ToolResult("Location unknown — ask the user where they are or to set their location on the Map.", label="Looked around", summary="Location unknown", ok=False)
    try:
        radius = float(args.get("radius_km") or 15)
    except (TypeError, ValueError):
        radius = 15.0
    radius = max(1.0, min(radius, 80.0))
    kind = str(args.get("kind") or "all")
    places = svc.location.nearby(loc["lat"], loc["lon"], radius_km=radius, kinds=None if kind == "all" else [kind], limit=12)
    if not places:
        return ToolResult(f"Nothing notable found within {radius:g} km.", label="Looked around", summary="Nothing found", ok=False)
    metric = svc.settings.device("general").units == "metric"
    lines, sources = [], []
    for p in places:
        dist = f"{p['distance_km']:.1f} km" if metric else f"{p['distance_km'] * 0.621371:.1f} mi"
        line = f"- {p['name']} ({p.get('kind') or 'place'}) — {dist} {p.get('direction', '')}"
        if p.get("wiki_path"):
            src = {"type": "library", "title": p["name"], "book": "wikipedia", "book_title": "Wikipedia", "collection": "encyclopedia",
                   "path": p["wiki_path"], "url": f"/library/read/wikipedia/{p['wiki_path']}", "snippet": p.get("kind") or ""}
            n = st.add_source(src)
            sources.append(src)
            line += f" [{n}]"
        lines.append(line)
    return ToolResult("Nearby:\n" + "\n".join(lines), label="Looked around nearby", summary=f"{len(places)} places", sources=sources, data={"places": places})


# --------------------------------------------------------------------------- math
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "log2", "exp", "floor", "ceil", "radians", "degrees", "hypot", "factorial")}
_FUNCS.update(abs=abs, round=round, min=min, max=max)
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("unsupported expression")


async def calculate(args: dict, st: TurnState, svc) -> ToolResult:
    expr = str(args.get("expression") or "").replace("^", "**").replace("×", "*").replace("÷", "/")
    try:
        value = _eval(ast.parse(expr, mode="eval"))
        if isinstance(value, float):
            value = round(value, 10)
        return ToolResult(f"{expr} = {value}", label="Calculated", summary=f"= {value}")
    except Exception as e:
        return ToolResult(f"Couldn't evaluate “{expr}”: {e}", label="Calculated", ok=False)


# --------------------------------------------------------------------------- registry
def _has_library(st, svc) -> bool:
    return svc.kiwix_service.alive()


TOOLS: list[Tool] = [
    Tool("search_library",
         "Search MIMI's offline reference library (Wikipedia, WikiMed, iFixit, Wikivoyage, survival guides, Stack Exchange, dictionary, books, TED talks). Returns numbered passages to cite as [n]. Use for any factual question.",
         _obj({"query": {"type": "string", "description": "Short keyword query, e.g. 'second degree burn first aid'"},
               "collection": {"type": "string", "enum": COLLECTION_ENUM, "description": "Which shelf to search; 'auto' picks based on the current mode"}}, ["query"]),
         search_library, _has_library),
    Tool("read_article",
         "Read more of one specific library article by its exact title when a search passage wasn't enough.",
         _obj({"title": {"type": "string"}, "collection": {"type": "string", "enum": COLLECTION_ENUM}}, ["title"]),
         read_article, _has_library),
    Tool("show_reference_image",
         "Look at the main picture from a library article — e.g. to compare it with the user's photo or to describe what something looks like.",
         _obj({"title": {"type": "string", "description": "Article title, e.g. 'Amanita muscaria'"}, "collection": {"type": "string", "enum": COLLECTION_ENUM}}, ["title"]),
         show_reference_image, lambda st, svc: _has_library(st, svc) and st.vision),
    Tool("search_my_files",
         "Search the user's own documents and Scribe voice notes.",
         _obj({"query": {"type": "string"}}, ["query"]),
         search_my_files, lambda st, svc: svc.docs.count(st.ctx.id) > 0),
    Tool("remember",
         "Save a lasting fact or preference about the user (e.g. 'Drives a 2014 Toyota Tacoma', 'Vegetarian'). Only for durable personal info, not for trivia.",
         _obj({"fact": {"type": "string", "description": "One short sentence in third person"},
               "category": {"type": "string", "enum": ["personal", "preference", "project", "other"]}}, ["fact"]),
         remember, lambda st, svc: svc.memory.enabled_for(st.ctx) and not st.temporary),
    Tool("where_am_i", "Get the device's current location (nearest town, region) from GPS or the location the user set.",
         _obj({}), where_am_i, lambda st, svc: svc.location.available()),
    Tool("nearby_places", "Find notable places near the current location: parks, landmarks, historic sites, towns, lakes, mountains.",
         _obj({"radius_km": {"type": "number", "description": "Search radius in km (default 15)"},
               "kind": {"type": "string", "enum": ["all", "nature", "history", "culture", "towns", "water", "mountains"]}}),
         nearby_places, lambda st, svc: svc.location.available()),
    Tool("calculate", "Evaluate an arithmetic expression exactly (supports + - * / ** % sqrt, sin, log, pi…).",
         _obj({"expression": {"type": "string"}}, ["expression"]), calculate),
]
BY_NAME = {t.name: t for t in TOOLS}


def schemas(st: TurnState, svc) -> list[dict]:
    out = []
    for t in TOOLS:
        try:
            if t.available(st, svc):
                out.append(t.schema())
        except Exception as e:  # a broken availability check must not break chat
            L.warning("availability check for %s failed: %s", t.name, e)
    return out


def parse_args(raw: str | dict | None) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except ValueError:
        # small models sometimes emit single quotes or trailing text
        try:
            v = ast.literal_eval(raw.strip())
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}


async def run(name: str, raw_args: str | dict | None, st: TurnState, svc) -> ToolResult:
    tool = BY_NAME.get(name)
    if not tool:
        return ToolResult(f"Unknown tool '{name}'.", label=f"Unknown tool {name}", ok=False)
    args = parse_args(raw_args)
    try:
        return await asyncio.wait_for(tool.run(args, st, svc), timeout=45)
    except asyncio.TimeoutError:
        return ToolResult("The tool took too long.", label=f"{name} timed out", ok=False)
    except Exception as e:
        L.exception("tool %s failed", name)
        return ToolResult(f"The tool failed: {e}", label=f"{name} failed", ok=False)
