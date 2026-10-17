"""Run the golden question set against a live Mimi and record what happened.

    python eval/run.py                                   # every question, the device's current main model
    python eval/run.py --model qwen3.5-9b                # switch the main model for the run, restore it after
    python eval/run.py --retrieval-only                  # library search only: Recall@k / MRR, no model needed
    python eval/run.py --domain medicine --limit 5       # a quick smoke run

Each question is one JSONL row in the results file (default eval/results/<date>-<model>.jsonl):
the answer, its sources (with the cited article's text, so citations can be checked
offline), the tool calls, and timings. Runs are resumable: rerunning skips questions
already answered without an error; pass --fresh to start over.

Authentication: on the device itself, Mimi signs loopback requests in as the owner
(device settings general.local_auto_login, on by default, unless general.require_pin).
Otherwise pass --user NAME --pin PIN, or --token with a session token.
Chats are created as temporary and deleted afterwards, so the run leaves no history.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import goldset

RESULTS = goldset.HERE / "results"


class EvalError(RuntimeError):
    pass


# --------------------------------------------------------------------------- client
class Mimi:
    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 600, transport: httpx.BaseTransport | None = None):
        headers = {"x-mimi-session": token} if token else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, transport=transport,
                                 timeout=httpx.Timeout(connect=10, read=timeout, write=60, pool=10))
        self._articles: dict[tuple[str, str], str] = {}

    def close(self) -> None:
        self.http.close()

    def _json(self, method: str, url: str, **kw) -> Any:
        r = self.http.request(method, url, **kw)
        if r.status_code == 401:
            raise EvalError("Mimi says: not signed in. Run this on the device itself (loopback auto sign-in), "
                            "or pass --user NAME --pin PIN, or --token.")
        if r.status_code >= 400:
            raise EvalError(f"{method} {url} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def login(self, name: str, secret: str) -> None:
        self._json("POST", "/api/auth/login", json={"name": name, "secret": secret})

    def me(self) -> dict:
        me = self._json("GET", "/api/auth/me")
        if not me.get("user"):
            raise EvalError("Mimi says: not signed in. Run this on the device itself (loopback auto sign-in), "
                            "or pass --user NAME --pin PIN, or --token.")
        return me

    def version(self) -> str:
        try:
            return self._json("GET", "/api/ping").get("version", "")
        except Exception:
            return ""

    def location_known(self) -> bool | None:
        try:
            return bool(self._json("GET", "/api/location").get("current"))
        except EvalError:
            return None

    def services_known(self) -> bool | None:
        """Does the device have the fuel/hospital table (it comes with offline directions)?"""
        try:
            return bool((self._json("GET", "/api/location").get("geodata") or {}).get("services"))
        except EvalError:
            return None

    # ---- models
    def main_model_setting(self) -> str | None:
        return self._json("GET", "/api/settings")["device"]["models"].get("main")

    def set_main_model(self, model: str | None, wait: float = 900) -> None:
        self._json("PATCH", "/api/settings/device/models", json={"main": model})
        if not model or wait <= 0:
            return
        start = time.time()
        while time.time() - start < wait:  # Mimi unloads and preloads the new main model in the background
            st = self._json("GET", "/api/models")["status"]
            if st.get("model") == model and st.get("status") == "ready":
                return
            if st.get("status") == "error" and st.get("model") == model:
                raise EvalError(f"{model} failed to load: {st.get('error')}")
            if st.get("status") != "loading" and time.time() - start > 15:
                return  # nothing is loading it (preload is off): the warm-up turn will
            time.sleep(2)
        raise EvalError(f"{model} did not finish loading within {wait:.0f} s")

    def warm_up(self, mode: str | None, think: bool | None) -> str | None:
        """One throwaway turn so model loading and prompt-cache filling don't land on the first question."""
        got = self.ask("Hello", mode=mode, think=think)
        msg = got.get("message") or {}
        if msg.get("chat_id"):
            self.delete_chat(msg["chat_id"])
        if got.get("error"):
            raise EvalError(f"warm-up turn failed: {got['error']}")
        return (msg.get("meta") or {}).get("model") or (got.get("meta") or {}).get("model")

    # ---- library
    def search(self, q: str, limit: int, collection: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"q": q, "limit": limit}
        if collection:
            params["collection"] = collection
        return self._json("GET", "/api/library/search", params=params)["results"]

    def article_text(self, book: str, path: str, max_chars: int) -> str:
        key = (book, path)
        if key not in self._articles:
            try:
                art = self._json("GET", f"/api/library/article/{quote(book)}/{quote(path, safe='/')}")
                self._articles[key] = html_to_text(art.get("html") or "")
            except EvalError:
                self._articles[key] = ""
        return self._articles[key][:max_chars]

    # ---- chat
    def ask(self, question: str, *, mode: str | None, think: bool | None) -> dict:
        """One turn over SSE. Returns the parsed events plus client-side timings."""
        body = {"content": question, "temporary": True, "mode": mode, "think": think}
        out: dict[str, Any] = {"deltas": 0, "tools": [], "error": None, "message": None, "meta": None, "statuses": []}
        t0 = time.perf_counter()
        ms = lambda: int((time.perf_counter() - t0) * 1000)
        starts: dict[str, dict] = {}
        with self.http.stream("POST", "/api/chats/new/messages", json=body) as r:
            if r.status_code == 401:
                raise EvalError("Mimi says: not signed in (see --help).")
            if r.status_code >= 400:
                raise EvalError(f"chat request failed: {r.status_code} {r.read()[:200]!r}")
            for event, data in sse_events(r.iter_lines()):
                out.setdefault("first_event_ms", ms())
                if event == "meta":
                    out["meta"] = data
                elif event == "delta":
                    out.setdefault("ttft_ms", ms())
                    out["deltas"] += 1
                elif event == "status":
                    out["statuses"].append({"state": data.get("state"), "ms": ms()})
                elif event == "tool":
                    if data.get("state") == "start":
                        out.setdefault("first_tool_ms", ms())
                        starts[data.get("id")] = {"name": data.get("name"), "args": data.get("args") or {}, "start_ms": ms()}
                    else:
                        s = starts.get(data.get("id"), {"name": data.get("name"), "args": {}})
                        out["tools"].append({**s, "label": data.get("label"), "summary": data.get("summary"), "ok": data.get("ok"),
                                             "ms": data.get("ms")})
                elif event == "error":
                    out["error"] = data.get("message")
                elif event == "done":
                    out["message"] = data.get("message")
        out["total_ms"] = ms()
        return out

    def delete_chat(self, chat_id: str) -> None:
        try:
            self.http.delete(f"/api/chats/{chat_id}")
        except httpx.HTTPError:
            pass


def sse_events(lines: Iterator[str]) -> Iterator[tuple[str, dict]]:
    """Parse a text/event-stream into (event, data) pairs; comments and keep-alives are skipped."""
    event, data = "message", []
    for line in lines:
        if line == "":
            if data:
                try:
                    yield event, json.loads("\n".join(data))
                except ValueError:
                    pass
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            yield event, json.loads("\n".join(data))
        except ValueError:
            pass


def html_to_text(html: str) -> str:
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for sel in ("script", "style", "table.infobox", "sup.reference", ".reference", ".mw-references-wrap", "figure"):
            for n in tree.css(sel):
                n.decompose()
        parts = []
        for n in tree.css("h1, h2, h3, h4, p, li, dd, blockquote, pre, td"):
            t = re.sub(r"\s+", " ", n.text(separator=" ")).strip()
            if t:
                parts.append(t)
        text = "\n".join(parts) if parts else (tree.body.text(separator=" ") if tree.body else "")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\[\d+\]|\[citation needed\]|\[edit\]", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# --------------------------------------------------------------------------- run
def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", (s or "default").lower()).strip("-") or "default"


def done_keys(path: Path) -> set[tuple[str, int]]:
    keys = set()
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not row.get("error"):
                keys.add((row["id"], int(row.get("rep", 0))))
    return keys


def select(items: list[dict], args) -> list[dict]:
    if args.ids:
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [it for it in items if it["id"] in want]
    if args.domain:
        doms = {d.strip() for d in args.domain.split(",")}
        items = [it for it in items if it["domain"] in doms]
    if args.retrieval_only:
        items = [it for it in items if it.get("titles") or it.get("collections")]
    return items[: args.limit] if args.limit else items


def chat_row(mimi: Mimi, item: dict, rep: int, args, run_id: str, location_known: bool | None, version: str,
             services_known: bool | None = None) -> dict:
    row: dict[str, Any] = {"run_id": run_id, "kind": "chat", "id": item["id"], "rep": rep, "domain": item["domain"],
                           "question": item["question"], "started_at": _now(), "mimi_version": version,
                           "location_known": location_known, "services_known": services_known, "mode": args.mode,
                           "think": args.think}
    try:
        got = mimi.ask(item["question"], mode=args.mode, think=args.think)
    except (httpx.HTTPError, EvalError) as e:
        row.update(error=f"{type(e).__name__}: {e}", answer="", sources=[], tools=[], timings={})
        return row
    msg = got.get("message") or {}
    meta = msg.get("meta") or {}
    first = got.get("meta") or {}
    sources = []
    for s in meta.get("sources") or []:
        src = {k: s.get(k) for k in ("n", "type", "title", "book", "book_title", "collection", "path", "url", "snippet")}
        if args.passages and s.get("type") == "library" and s.get("book") and s.get("path"):
            src["text"] = mimi.article_text(s["book"], s["path"], args.passage_chars)
        sources.append(src)
    st = meta.get("timings") or {}
    row.update(
        model=meta.get("model") or first.get("model"), model_name=meta.get("model_name") or first.get("model_name"),
        mode=meta.get("mode") or args.mode, answer=msg.get("content") or "", sources=sources, tools=got["tools"],
        timings={"first_event_ms": got.get("first_event_ms"), "ttft_ms": got.get("ttft_ms"), "first_tool_ms": got.get("first_tool_ms"),
                 "total_ms": got["total_ms"], "server_total_ms": st.get("total_ms"),
                 **{k: st[k] for k in ("predicted_per_second", "prompt_per_second", "predicted_n", "prompt_n") if k in st}},
        cancelled=meta.get("cancelled"), error=got.get("error") or meta.get("error"),
    )
    if msg.get("chat_id") and not args.keep_chats:
        mimi.delete_chat(msg["chat_id"])
    return row


def retrieval_row(mimi: Mimi, item: dict, args, run_id: str, version: str) -> dict:
    q = item["question"] if args.query_field == "question" else (item.get("query") or item["question"])
    row: dict[str, Any] = {"run_id": run_id, "kind": "retrieval", "id": item["id"], "rep": 0, "domain": item["domain"],
                           "question": item["question"], "query": q, "started_at": _now(), "mimi_version": version,
                           "model": "retrieval", "error": None}
    t0 = time.perf_counter()
    try:
        hits = mimi.search(q, args.k)
    except (httpx.HTTPError, EvalError) as e:
        row.update(error=f"{type(e).__name__}: {e}", results=[], ms=None)
        return row
    row["ms"] = int((time.perf_counter() - t0) * 1000)
    row["results"] = [{"rank": i + 1, "title": h.get("title"), "book": h.get("book"), "collection": h.get("collection"),
                       "path": h.get("path"), "score": h.get("score")} for i, h in enumerate(hits)]
    return row


def run(args, transport: httpx.BaseTransport | None = None, log=print) -> Path:
    items = goldset.load(args.questions)
    problems = goldset.validate(items)
    if problems:
        raise EvalError("question set is invalid:\n  " + "\n  ".join(problems[:20]))
    items = select(items, args)
    mimi = Mimi(args.base_url, token=args.token, timeout=args.timeout, transport=transport)
    restore: tuple[bool, str | None] = (False, None)
    try:
        if args.user:
            mimi.login(args.user, args.pin or "")
        mimi.me()
        version = mimi.version()
        if args.model and not args.retrieval_only:
            restore = (True, mimi.main_model_setting())
            log(f"switching the main model to {args.model} …")
            mimi.set_main_model(args.model)
        if not args.retrieval_only and args.warmup:
            served = mimi.warm_up(args.mode, args.think)
            if args.model and served and served != args.model:
                raise EvalError(f"Mimi answered with {served}, not {args.model} (battery saver maps the main model to the quick one)")
        label = "retrieval" if args.retrieval_only else (args.model or "default")
        out = Path(args.out) if args.out else RESULTS / f"{datetime.now():%Y-%m-%d}-{_slug(label)}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.fresh and out.exists():
            out.unlink()
        done = done_keys(out)
        run_id = uuid.uuid4().hex[:12]
        location_known = None if args.retrieval_only else mimi.location_known()
        services_known = None if args.retrieval_only else mimi.services_known()
        reps = 1 if args.retrieval_only else max(1, args.repeats)
        todo = [(it, rep) for rep in range(reps) for it in items if (it["id"], rep) not in done]
        log(f"{len(todo)} to run ({len(done)} already in {out})")
        with out.open("a", encoding="utf-8") as f:
            for i, (it, rep) in enumerate(todo, 1):
                row = retrieval_row(mimi, it, args, run_id, version) if args.retrieval_only else \
                    chat_row(mimi, it, rep, args, run_id, location_known, version, services_known)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                took = row.get("ms") if args.retrieval_only else (row.get("timings") or {}).get("total_ms")
                log(f"[{i}/{len(todo)}] {it['id']}{f' #{rep}' if reps > 1 else ''}: "
                    f"{'ERROR ' + row['error'] if row.get('error') else 'ok'} ({(took or 0) / 1000:.1f} s)")
        return out
    finally:
        if restore[0]:
            try:
                log(f"restoring the main model setting ({restore[1] or 'automatic'})")
                mimi.set_main_model(restore[1], wait=0)
            except Exception as e:  # never hide the run's own error behind this one
                log(f"could not restore the model setting: {e}")
        mimi.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run Mimi's golden question set against a live Mimi.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:7600", help="Mimi Core (default: %(default)s)")
    p.add_argument("--questions", default=None, help="JSONL file or glob (default: eval/questions/*.jsonl)")
    p.add_argument("--out", default=None, help="results JSONL (default: eval/results/<date>-<model>.jsonl)")
    p.add_argument("--model", default=None, help="model id to use as the main model for this run (e.g. gemma-4-12b, qwen3.5-9b)")
    p.add_argument("--mode", default=None, help="chat mode (everyday, field_medic, fix_it, …); default: the user's default mode")
    p.add_argument("--think", action=argparse.BooleanOptionalAction, default=None, help="force 'think harder' on/off")
    p.add_argument("--retrieval-only", action="store_true", help="only hit /api/library/search (Recall@k, MRR)")
    p.add_argument("--query-field", choices=("query", "question"), default="query",
                   help="retrieval: search with the item's keyword query (default) or the raw question")
    p.add_argument("--k", type=int, default=10, help="retrieval: results to fetch (default: %(default)s)")
    p.add_argument("--ids", default=None, help="comma-separated item ids")
    p.add_argument("--domain", default=None, help="comma-separated domains")
    p.add_argument("--limit", type=int, default=0, help="run at most N items")
    p.add_argument("--repeats", type=int, default=1, help="ask every question N times (sampling variance)")
    p.add_argument("--fresh", action="store_true", help="discard an existing results file instead of resuming")
    p.add_argument("--passages", action=argparse.BooleanOptionalAction, default=True,
                   help="fetch each cited article's text so citations can be checked (default: on)")
    p.add_argument("--passage-chars", type=int, default=20000, help="max article characters kept per source")
    p.add_argument("--keep-chats", action="store_true", help="don't delete the temporary chats afterwards")
    p.add_argument("--warmup", action=argparse.BooleanOptionalAction, default=True,
                   help="send one throwaway turn first so model loading isn't timed (default: on)")
    p.add_argument("--timeout", type=float, default=600, help="seconds to wait for one answer")
    p.add_argument("--token", default=None, help="session token (x-mimi-session)")
    p.add_argument("--user", default=None, help="sign in with this user name …")
    p.add_argument("--pin", default=None, help="… and this PIN or password")
    return p


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        out = run(args, transport=transport)
    except EvalError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except httpx.ConnectError:
        print(f"error: can't reach Mimi at {args.base_url}. Is it running?", file=sys.stderr)
        return 2
    print(f"results: {out}\nscore with: python eval/score.py {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
