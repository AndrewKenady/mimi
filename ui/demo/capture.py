"""Record the browser demo's data from the real Mimi Core.

The demo on GitHub Pages (npm run build:demo) has no Core behind it. Instead it answers the
app's requests from ui/src/lib/demo/recorded.json, which this script records from the real
Core API: the same FastAPI routes, auth, chat turn loop, citation check, settings and SQLite
database as a device, with the scripted model and small library of the end-to-end fixture
(ui/e2e/fixture_core.py). Nothing in recorded.json is written by hand.

    python ui/demo/capture.py [--maps DIR] [--out ui/src/lib/demo/recorded.json]

What is recorded:
  * every GET the UI makes on each screen (found by grepping ui/src for get()/api() and by
    watching a Playwright crawl of every screen; see ROUTES below),
  * three chat turns as Server-Sent Events with their timing, at the reference handheld's
    pace (about 8 tokens/s): a grounded answer, one with a claim its source doesn't support,
    and small talk,
  * a few library searches a visitor would try,
  * with --maps DIR (tiles.pmtiles + tiles.json, world.pmtiles + world.json, routing/ and
    places.sqlite for an area), the map's info, places near the seeded location, place
    searches and one driving route. ui/demo/maps/ holds the same tiles for the demo to show.

Run it with the Core's Python (core/ deps installed). --maps also needs pyvalhalla importable.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "ui" / "e2e"))

import fixture_core as fx
import httpx
import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from mimi import hardware
from mimi.app import create_app
from mimi.paths import Paths

OUT = ROOT / "ui" / "src" / "lib" / "demo" / "recorded.json"

# The questions the demo can answer. `mode` picks the fixture's scripted model; `match` lists
# the words a visitor's own question must contain for the demo to replay this turn.
SCENARIOS = [
    {"id": "grounded", "mode": "grounded", "question": "How do I treat hypothermia?",
     "title": "Treating hypothermia in the field", "match": [["hypotherm", "cold", "freez", "chill", "shiver"]]},
    {"id": "flagged", "mode": "ungrounded", "question": "Can a hot bath treat hypothermia?",
     "title": "Hot baths for hypothermia", "match": [["hypotherm", "cold", "freez", "chill", "shiver"], ["bath", "hot water", "tub", "soak"]]},
    {"id": "chitchat", "mode": "chitchat", "question": "Hi Mimi!",
     "title": "Hello", "match": [["hi", "hello", "hey", "howdy", "morning", "evening", "afternoon", "yo"]]},
]
SEARCHES = ["hypothermia", "frostbite", "space blanket", "cold", "first aid"]
MEMORIES = [
    ("Ada keeps a first-aid kit and two space blankets in the truck.", "personal", "active"),
    ("Prefers short answers with numbered steps.", "preference", "active"),
    ("Ada is planning a winter trip through Yellowstone and Grand Teton.", "project", "suggested"),
]
# Old Faithful, Yellowstone; the recorded route goes from here to Jackson, Wyoming.
HOME = {"lat": 44.4605, "lon": -110.8281, "label": "Old Faithful"}
DEST = {"lat": 43.4799, "lon": -110.7624, "name": "Jackson"}
PLACE_SEARCHES = ["Jackson", "Old Faithful", "Grand Teton"]

# Every GET the UI makes (ui/src: get(…)/api(…); then a Playwright crawl of each screen).
# Query strings are written exactly as the UI builds them; keys are normalised anyway.
ROUTES = [
    "/api/bootstrap", "/api/ping", "/api/health", "/api/auth/me",
    "/api/settings", "/api/settings/export",
    "/api/chats", "/api/chats?archived=true",
    "/api/library/books", "/api/library/books?all=true",
    "/api/library/random",
    "/api/memories", "/api/scribe", "/api/files",
    "/api/location", "/api/location/nearby?limit=4&radius=25",
    "/api/maps/info", "/api/route/status",
    "/api/models", "/api/tools", "/api/voice/voices", "/api/users",
    "/api/system", "/api/system/logs/core.log?lines=120",
    "/api/share", "/api/share/qr?kind=wifi", "/api/share/qr?kind=url",
]
ARTICLES = ["wikimed/A/Hypothermia", "wikimed/A/Frostbite", "wikipedia/A/Space_blanket"]


def key(path: str) -> str:
    """The lookup key the demo uses: path plus sorted query (so param order doesn't matter)."""
    u = urllib.parse.urlsplit(path)
    q = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
    return u.path + ("?" + urllib.parse.urlencode(sorted(q)) if q else "")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_core(data: Path, content: Path, port: int):
    """The fixture Core (real API, scripted model, small library), in this process."""
    import os

    os.environ["MIMI_CONTENT"] = str(content)
    app = create_app(Paths(data_override=data))
    svc = app.state.svc
    TestClient(app).post("/api/auth/setup", json={"name": "Ada"})
    fx.install(svc, 1.0)  # speed 1: the reference handheld's pace
    # What the (skipped) startup would do: open places.sqlite if there is one, probe the hardware.
    svc.location.reload_geodata()
    svc.hw.update(hardware.detect(svc.paths, False))

    @app.get("/__fixture/login")
    async def login(to: str = "/"):
        tok = svc.auth.create_session(svc.auth.list()[0]["id"], "demo")
        r = RedirectResponse(to if to.startswith("/") else "/")
        r.set_cookie("mimi_session", tok, httponly=True)
        return r

    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the SPA catch-all
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    return svc, server


def record_get(c: httpx.Client, path: str) -> dict:
    t = time.perf_counter()
    r = c.get(path)
    ms = round((time.perf_counter() - t) * 1000)
    ct = r.headers.get("content-type", "")
    body = r.json() if "json" in ct else r.text
    return {"status": r.status_code, "type": ct.split(";")[0], "ms": ms, "body": body}


def stream_turn(c: httpx.Client, chat: str, body: dict) -> list:
    """POST a message and keep each SSE event with its offset in ms from the request."""
    events = []
    t0 = time.perf_counter()
    with c.stream("POST", f"/api/chats/{chat}/messages", json=body, headers={"accept": "text/event-stream"}) as s:
        buf = ""
        for chunk in s.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                ev, data = "message", []
                for line in block.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                if data and ev != "message":
                    events.append([round((time.perf_counter() - t0) * 1000), ev, json.loads("\n".join(data))])
    return events


def templatize(obj, ids: dict[str, str]):
    """Swap this run's ids for placeholders the demo fills in on replay."""
    s = json.dumps(obj)
    for real, ph in ids.items():
        s = s.replace(real, ph)
    return json.loads(s)


def scrub(obj, tokens: list[tuple[str, str]]):
    s = json.dumps(obj)
    for a, b in tokens:
        s = s.replace(json.dumps(a)[1:-1], json.dumps(b)[1:-1])
    return json.loads(s)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--maps", type=Path, help="a maps folder for a small area (tiles/world .pmtiles + .json, routing/, places.sqlite)")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="mimi-demo-"))
    data, content = tmp / "data", tmp / "content"
    data.mkdir()
    (content / "maps").mkdir(parents=True)
    if args.maps:
        for f in ("tiles.pmtiles", "tiles.json", "world.pmtiles", "world.json", "places.sqlite", "routing"):
            if (args.maps / f).exists():
                (content / "maps" / f).symlink_to((args.maps / f).resolve())
    port = free_port()
    svc, server = start_core(data, content, port)
    base = f"http://127.0.0.1:{port}"
    c = httpx.Client(base_url=base, timeout=120)
    c.get("/__fixture/login?to=/")
    out: dict = {"version": 1, "captured": time.strftime("%Y-%m-%d"), "get": {}, "chats": [], "searches": SEARCHES}
    print(f"Core on {base}, data in {tmp}")

    # --- a lived-in profile, set up through the API like a person would --------------------
    for text, cat, status in MEMORIES:
        m = c.post("/api/memories", json={"text": text, "category": cat}).json()
        if status != "active":
            c.patch(f"/api/memories/{m['id']}", json={"status": status})
    if args.maps:
        c.post("/api/location", json={**{k: HOME[k] for k in ("lat", "lon")}, "label": HOME["label"], "manual": True})

    # --- chat turns, with timing -----------------------------------------------------------
    for sc in SCENARIOS:
        fx.MODE["value"] = sc["mode"]
        print(f"  chat: {sc['question']} ({sc['mode']})", flush=True)
        events = stream_turn(c, "new", {"content": sc["question"], "mode": "everyday"})
        meta = next(d for _, ev, d in events if ev == "meta")
        cid, uid, aid = meta["chat_id"], meta["user_message"]["id"], meta["assistant_message_id"]
        c.patch(f"/api/chats/{cid}", json={"title": sc["title"]})
        thread = c.get(f"/api/chats/{cid}").json()
        c.delete(f"/api/chats/{cid}")  # the demo starts with an empty history
        ids = {cid: "{{chat}}", uid: "{{user}}", aid: "{{assistant}}"}
        out["chats"].append({k: sc[k] for k in ("id", "question", "title", "match")} | {
            "events": templatize(events, ids), "thread": templatize(thread, ids)})

    # --- every screen's GETs ------------------------------------------------------------------
    paths = list(ROUTES)
    books = c.get("/api/library/books?all=true").json()["books"]
    for b in books:
        paths.append(f"/api/library/home/{b['alias']}")
        if b.get("kind") and b["kind"] != "articles":
            paths.append(f"/api/library/collection/{urllib.parse.quote(b['alias'])}?offset=0&limit=120")
    for a in ARTICLES:
        bk, p = a.split("/", 1)
        paths.append(f"/api/library/article/{bk}/{p}")
    for q in SEARCHES:
        paths.append("/api/library/search?" + urllib.parse.urlencode({"q": q, "limit": "16"}))
    paths += [f"/api/memories?q={urllib.parse.quote(q)}" for q in ("trip", "kit")]
    if args.maps:
        paths.append(f"/api/location/nearby?lat={HOME['lat']}&lon={HOME['lon']}&radius=30&kind=all&limit=30")
        for k in ("nature", "history", "towns", "water", "mountains"):
            paths.append(f"/api/location/nearby?lat={HOME['lat']}&lon={HOME['lon']}&radius=30&kind={k}&limit=30")
        paths += ["/api/location/search?" + urllib.parse.urlencode({"q": q}) for q in PLACE_SEARCHES]
    for p in paths:
        out["get"][key(p)] = record_get(c, p)

    # --- the one recorded route -----------------------------------------------------------------
    if args.maps:
        r = c.post("/api/route", json={"to": {"lat": DEST["lat"], "lon": DEST["lon"]}})
        out["route"] = {"to": DEST, "status": r.status_code, "body": r.json()}
        print(f"  route to {DEST['name']}: {r.status_code}")

    # --- live events Core sends a new WebSocket (sticky ones: location, model…) ----------------
    out["events"] = [ev for ev in svc.events.last.values()] if hasattr(svc.events, "last") else []

    server.should_exit = True
    # Nothing local leaks into a public page: this machine's paths become the device's.
    out = scrub(out, [(str(tmp), "/opt/mimi/data"), (str(ROOT), "/opt/mimi"), (str(Path.home()), "/home/mimi")])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print(f"Wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB, {len(out['get'])} GETs, {len(out['chats'])} chat turns)")
    shutil.rmtree(tmp, ignore_errors=True)
    if re.search(r"/home/user|/tmp/", args.out.read_text("utf-8")):
        print("  ! a local path is still in the recording; check scrub()")


if __name__ == "__main__":
    main()
