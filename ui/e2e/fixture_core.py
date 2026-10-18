"""The real Mimi Core API with a scripted model and a small fake library, for end-to-end tests.

Everything above the model and kiwix-serve is real: FastAPI routes, auth, the chat turn loop,
tool calling, the citation check, settings and the SQLite database. Only the two engines that
need gigabytes of weights and content are replaced, so the UI can be driven in CI on any OS.

    python ui/e2e/fixture_core.py [--port 7671] [--speed 8] [--data DIR]

Speed 1 paces the model like the reference handheld (about 8 tok/s, a 9 s read), which is what
the screenshots in docs/ use; the test suite runs faster. POST /__fixture/mode/<mode> switches
the scripted answer: grounded (default), ungrounded (one claim its source doesn't support),
error, or chitchat.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from mimi import llm
from mimi.app import create_app
from mimi.kiwix import Book, Hit, Passage, alias_of
from mimi.libindex import Doc
from mimi.paths import Paths

HYPO = (
    "Hypothermia is defined as a body core temperature below 35.0 °C (95.0 °F) in humans. Symptoms depend on the temperature.\n"
    "## Signs and symptoms\n"
    "In mild hypothermia, there is shivering and mental confusion. In moderate hypothermia, shivering stops and confusion increases.\n"
    "## Management\n"
    "Treatment of mild hypothermia involves warm drinks, warm clothing, and voluntary physical activity. "
    "In those with moderate hypothermia, heating blankets and warmed intravenous fluids are recommended. "
    "Rescuers should handle the person gently, since rough movement can trigger a dangerous heart rhythm."
)
ARTICLES = {
    "Hypothermia": ("wikimed", "medicine", HYPO, "#2f7f86"),
    "Frostbite": ("wikimed", "medicine", "Frostbite is a skin injury that occurs when exposed to extreme low temperatures, "
                  "most commonly in the fingers, toes, nose and ears. Rewarming should not be done by rubbing the skin.", None),
    "Space blanket": ("wikipedia", "encyclopedia", "A space blanket is an especially low-weight, low-bulk blanket made of "
                      "heat-reflective thin plastic sheeting, used to reduce heat loss from a person's body.", "#8a6d3b"),
}


def _book(name: str, title: str, collection: str, summary: str, kind: str = "articles", items: int = 0, size: int = 0) -> Book:
    return Book(id=name, name=name, alias=alias_of(name), title=title, summary=summary, language="eng", category="", tags="",
                flavour="", articles=items if kind == "articles" else 1, media=0, collection=collection, icon=None,
                file=name + ".zim", size=size, kind=kind, items=items, main="A/Main_Page")


BOOKS = [
    _book("wikimed", "WikiMed Medical Encyclopedia", "medicine", "Medical articles from Wikipedia, checked by WikiProjectMed.",
          items=73_412, size=2_300 << 20),
    _book("zimgit-medicine_en_2024-08", "Medical Library", "medicine", "A collection of books pertaining to field and emergency medicine.",
          kind="documents", items=12, size=67 << 20),
    _book("wikipedia", "Wikipedia", "encyclopedia", "The free encyclopedia.", items=6_912_000, size=118 << 30),
    _book("ted_mul_medicine_2025-01", "TED Medicine", "talks", "TED talks about medicine.", kind="videos", items=212, size=3_600 << 20),
    _book("gutenberg_en_lcc-pa_2025-01", "Project Gutenberg: Classics", "books", "Greek and Latin classics.", kind="books",
          items=0, size=520 << 20),
]
HEALTH = {
    "wikimed": {"status": "ok", "readable": True, "searchable": True, "note": ""},
    "zimgit-medicine_en_2024-08": {"status": "ok", "readable": True, "searchable": True, "note": "3,138 pages searchable"},
    "wikipedia": {"status": "ok", "readable": True, "searchable": True, "note": ""},
    "ted_mul_medicine_2025-01": {"status": "limited", "readable": True, "searchable": False,
                                 "note": "Talks can be browsed and played; their words aren't searchable."},
    "gutenberg_en_lcc-pa_2025-01": {"status": "unreadable", "readable": False, "searchable": False,
                                    "note": "This file looks damaged: its book list couldn't be read. Re-download it in Settings."},
}
DOCS = [
    Doc(id=str(i), title=t, path=f"files/{t}.pdf", kind="pdf", author=a, description=d, mime="application/pdf", size=mb << 20,
        pages=pg, indexed=pg > 0)
    for i, (t, a, d, mb, pg) in enumerate([
        ("Emergency War Surgery", "US Department of Defense", "Dedicated to the Combat Physician", 7, 484),
        ("A Book for Midwives", "Susan Klein, Suellen Miller, and Fiona Thomson", "Care for pregnancy, birth, and women's health", 13, 544),
        ("First Aid", "US Departments of the Army, the Navy, and the Air Force", "Field Manual", 2, 224),
        ("HHS Pandemic Influenza Plan", "U.S. Department of Health and Human Services", "A blueprint for pandemic preparedness", 6, 380),
        ("Wound Closure Manual", "Ethicon", "", 3, 0),
        ("Where There Is No Doctor", "David Werner", "A village health care handbook", 14, 446),
        ("Where There Is No Dentist", "Murray Dickson", "", 5, 208),
        ("Wilderness Medicine Course", "", "", 4, 160),
        ("Hesperian Helping Health Workers Learn", "David Werner and Bill Bower", "", 9, 632),
        ("Ship Captain's Medical Guide", "Maritime and Coastguard Agency", "", 4, 300),
        ("Special Operations Forces Medical Handbook", "US Special Operations Command", "", 8, 560),
        ("The Survival Medicine Handbook", "Joseph Alton and Amy Alton", "", 6, 0),
    ], 1)
]


def thumb(color: str | None) -> str | None:
    if not color:
        return None
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'><defs><linearGradient id='g' x2='1' y2='1'>"
           f"<stop offset='0' stop-color='{color}'/><stop offset='1' stop-color='#0b1418'/></linearGradient></defs>"
           f"<rect width='40' height='40' fill='url(#g)'/><circle cx='28' cy='12' r='6' fill='#ffffff' opacity='.35'/></svg>")
    return "data:image/svg+xml," + urllib.parse.quote(svg)


class _NoKiwixServe:
    """Stands in for the HTTP client to kiwix-serve: /random lands on a short article, which
    Home's Discover card passes over, exactly as on a library with no illustrated long reads."""

    async def get(self, url, params=None, follow_redirects=False):
        return SimpleNamespace(status_code=302, headers={"location": "/content/wikipedia/A/Space_blanket"}, text="")


class FixtureKiwix:
    """The slice of KiwixClient the routes and tools use, over the tables above."""

    def __init__(self, speed: float):
        self.speed = speed
        self.index_state = {"state": "done", "done": 12, "total": 12, "current": ""}
        self.http = _NoKiwixServe()

    def invalidate(self) -> None:
        pass

    async def books(self, include_disabled: bool = False) -> list[Book]:
        return list(BOOKS)

    async def book(self, name: str) -> Book | None:
        return next((b for b in BOOKS if name in (b.name, b.alias)), None)

    def health_of(self, b: Book) -> dict:
        return dict(HEALTH[b.name])

    async def collection(self, name: str):
        b = await self.book(name)
        return (b, list(DOCS)) if b and b.kind == "documents" else (b, []) if b else None

    async def search(self, q, collections=None, books=None, limit=5, local=None):
        await asyncio.sleep(0.9 / self.speed)
        bt = {b.name: b.title for b in BOOKS}
        return [Hit(title=t, path=f"A/{t.replace(' ', '_')}", book=bk, book_title=bt[bk], collection=c, snippet=text[:160])
                for t, (bk, c, text, _) in ARTICLES.items()][:limit]

    async def suggest(self, q, book, count=8):
        return []

    async def passage(self, hit, q, chars):
        bk, c, text, color = ARTICLES[hit.title]
        return Passage(title=hit.title, book=bk, book_title=hit.book_title, collection=c, path=hit.path, text=text,
                       image=thumb(color), url=f"/library/read/{bk}/{hit.path}")

    async def reader(self, book: str, path: str) -> dict | None:
        title = urllib.parse.unquote(path.split("/")[-1]).replace("_", " ")
        if title not in ARTICLES:
            return None
        bk, _, text, color = ARTICLES[title]
        paras = []
        for line in text.split("\n"):
            paras.append(f"<h2 id='{line[3:].lower().replace(' ', '-')}'>{line[3:]}</h2>" if line.startswith("## ") else f"<p>{line}</p>")
        toc = [{"id": line[3:].lower().replace(" ", "-"), "title": line[3:]} for line in text.split("\n") if line.startswith("## ")]
        b = await self.book(bk)
        return {"title": title, "book": bk, "alias": bk, "book_title": b.title if b else bk, "path": path, "html": "".join(paras),
                "image": thumb(color), "toc": toc}


ANSWER = (
    "Warm the person **gradually** and handle them gently [1].\n\n"
    "1. **Get out of the cold.** Move them somewhere sheltered and give them warm clothing [1].\n"
    "2. **Insulate.** A space blanket is a light, heat-reflective sheet that reduces heat loss [3].\n"
    "3. **Warm drinks** if they are alert and can swallow [1].\n"
    "4. **Don't rub the skin.** Rough movement can trigger a dangerous heart rhythm, and frostbitten skin shouldn't be rubbed [1][2].\n\n"
    "If shivering stops and confusion increases, that is **moderate hypothermia**: heating blankets and warmed intravenous "
    "fluids are recommended, so get help as fast as you can [1]."
)
# One claim the passage doesn't support: an invented temperature and duration.
UNGROUNDED = ANSWER.replace(
    "3. **Warm drinks** if they are alert and can swallow [1].",
    "3. **Warm bath:** put them in water at 45 °C for 3 hours [1].",
)
MODE = {"value": "grounded"}


def install(svc, speed: float) -> None:
    spec = SimpleNamespace(id="gemma-4-12b", name="Gemma 4 12B", vision=False, get=lambda k, d=None: 8192 if k == "context" else d)
    mm = svc.models
    mm.model_for = lambda role: spec
    mm.chat_model = spec
    mm.chat_proc = SimpleNamespace(alive=lambda: True)
    mm.chat_ctx = 8192

    async def ensure(s):
        pass

    mm.unload = mm.preload = lambda: ensure(None)  # a profile change reloads models; the script has none

    async def chat_once(*a, **k):
        return "Treating hypothermia in the field"

    async def chat_stream(s, messages, tools=None, cancel=None, **kw):
        mode = MODE["value"]
        if mode == "error":
            await asyncio.sleep(1.5 / speed)
            raise llm.ModelError("The language model stopped responding. It may be out of memory.")
        has_tool = any(m.get("role") == "tool" for m in messages)
        if tools and not has_tool and mode in ("grounded", "ungrounded"):
            await asyncio.sleep(3.2 / speed)
            yield {"type": "tool_calls", "calls": [{"id": "t1", "name": "search_library", "arguments": '{"query": "hypothermia treatment"}'}]}
            yield {"type": "done", "timings": {"prompt_n": 420, "prompt_per_second": 32.0}}
            return
        await asyncio.sleep((9.0 if has_tool else 1.2) / speed)
        text = (UNGROUNDED if mode == "ungrounded" else ANSWER) if has_tool else "Hi! I'm here, all offline. What do you need?"
        words = text.split(" ")
        for i, w in enumerate(words):
            if cancel and cancel.is_set():
                break
            yield {"type": "content", "text": w + (" " if i < len(words) - 1 else "")}
            await asyncio.sleep(0.12 / speed)
        yield {"type": "done", "timings": {"prompt_n": 1350, "prompt_per_second": 108.0, "predicted_n": len(words), "predicted_per_second": 8.2}}

    mm.ensure = ensure
    mm.chat_once = chat_once
    mm.chat_stream = chat_stream
    svc.kiwix = FixtureKiwix(speed)
    svc.kiwix_service.alive = lambda: True
    # one download that stopped halfway: held back from the shelf, and the library says so
    svc.kiwix_service.incomplete = [{"file": "wiktionary_en_all_nopic_2026-07.zim", "size": 4_100 << 20, "expected": 9_160 << 20}]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=7671)
    ap.add_argument("--speed", type=float, default=1.0, help=">1 runs faster than the reference device")
    ap.add_argument("--data", type=Path, default=None, help="data folder (default: a fresh temporary one)")
    args = ap.parse_args()
    data = args.data or Path(tempfile.mkdtemp(prefix="mimi-e2e-"))
    app = create_app(Paths(data_override=data))
    svc = app.state.svc
    if not svc.auth.list():
        TestClient(app).post("/api/auth/setup", json={"name": "Ada"})
    install(svc, args.speed)

    @app.post("/__fixture/mode/{mode}")
    async def set_mode(mode: str):
        MODE["value"] = mode
        return MODE

    @app.get("/__fixture/login")
    async def login(to: str = "/"):
        """A phone-style session for the owner (the fixture isn't on loopback's app port)."""
        tok = svc.auth.create_session(svc.auth.list()[0]["id"], "e2e")
        r = RedirectResponse(to if to.startswith("/") else "/")
        r.set_cookie("mimi_session", tok, httponly=True)
        return r

    # The SPA catch-all would shadow routes registered after it; move these two to the front.
    app.router.routes.insert(0, app.router.routes.pop())
    app.router.routes.insert(0, app.router.routes.pop())
    uvicorn.run(app, host="127.0.0.1", port=args.port, lifespan="off", log_level="warning")


if __name__ == "__main__":
    main()
