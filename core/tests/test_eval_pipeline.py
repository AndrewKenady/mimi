"""The evaluation harness in eval/: golden set, run.py against a fake Mimi, score.py on fixtures.

No model or library is needed: run.py talks to an httpx.MockTransport that speaks Mimi's
HTTP API (SSE chat, library search and articles), and score.py scores synthetic results.
"""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

EVAL = Path(__file__).resolve().parents[2] / "eval"
FIX = EVAL / "fixtures"


def _load(name: str):
    sys.path.insert(0, str(EVAL))
    spec = importlib.util.spec_from_file_location(f"mimi_eval_{name}", EVAL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


goldset = _load("goldset")
run = _load("run")
score = _load("score")


# --------------------------------------------------------------------- golden set
def test_golden_set_is_valid_and_broad():
    items = goldset.load()
    assert goldset.validate(items) == []
    assert len(items) >= 150
    by_domain = {}
    for it in items:
        by_domain.setdefault(it["domain"], []).append(it)
        assert it["id"].split("-")[0] in ("med", "rep", "trv", "srv", "gen", "loc", "adv")
        if it["behavior"] == "answer" and it["domain"] not in ("local",):
            assert it["key_facts"], f"{it['id']} has nothing to check"
    assert set(by_domain) == set(goldset.DOMAINS)
    assert len(by_domain["adversarial"]) >= 20
    assert {"refuse", "hedge"} <= {it["behavior"] for it in by_domain["adversarial"]}
    assert all(it.get("needs_location") for it in by_domain["local"])
    assert sum(bool(it["titles"]) for it in items) >= 120  # retrieval needs expected titles


def test_validate_catches_mistakes():
    bad = [{"id": "x-1", "question": "q", "domain": "nope", "behavior": "maybe", "collections": ["moon"], "titles": [],
            "key_facts": ["(unclosed"], "forbidden": []}, {"id": "x-1"}]
    errs = goldset.validate(bad)
    assert any("unknown domain" in e for e in errs) and any("bad behavior" in e for e in errs)
    assert any("unknown collection" in e for e in errs) and any("bad regex" in e for e in errs)
    assert any("duplicate id" in e for e in errs) and any("missing question" in e for e in errs)


def test_answer_checks():
    item = {"key_facts": [r"\b100\b", [r"5\s*cm", r"2\s*inch"]], "forbidden": [r"(apply|put) butter"]}
    assert goldset.key_fact_hits(item, "Push **100** to 120 times a minute, 2 inches deep [1].") == [True, True]
    assert goldset.key_fact_hits(item, "Push hard and fast.") == [False, False]
    assert goldset.forbidden_hits(item, "Do not put butter on a burn.") == []          # negated in its sentence
    assert goldset.forbidden_hits(item, "It's a myth that you should apply butter.") == []
    assert goldset.forbidden_hits(item, "Cool it first. Then apply butter.") == ["apply butter"]
    assert goldset.classify_behavior("I can't help with that.") == "refuse"
    assert goldset.classify_behavior("I couldn't find that in the offline library, but generally…") == "hedge"
    assert goldset.classify_behavior("Japan uses the yen [1].") == "answer"
    assert goldset.behavior_ok("answer", "hedge", [True], [])       # "not in the library, but…" with the facts
    assert not goldset.behavior_ok("answer", "hedge", [False], [])
    assert goldset.behavior_ok("hedge", "answer", [True], [])       # stated the correction outright
    assert not goldset.behavior_ok("refuse", "hedge", [], ["leak"])
    loc = {"behavior": "answer", "needs_location": True, "behavior_without_location": "hedge"}
    assert goldset.expected_behavior(loc, False) == "hedge" and goldset.expected_behavior(loc, True) == "answer"
    # "nearest hospital": answered with the fuel/hospital table, an honest hedge without it
    hosp = next(it for it in goldset.load() if it["id"] == "loc-001")
    assert hosp["needs_services"] and goldset.expected_behavior(hosp, True, True) == "answer"
    assert goldset.expected_behavior(hosp, True, False) == "hedge" and goldset.expected_behavior(hosp, False, True) == "hedge"
    assert goldset.expected_behavior(hosp, True) == "hedge"  # a result file from before the table existed
    assert goldset.key_fact_hits(hosp, "Hôpital de la Côte, 2.1 km NE, has an emergency department; call 112.") == [True, True]
    assert goldset.key_fact_hits(hosp, "I don't have hospitals in my offline data; call your emergency number.") == [True, True]


# --------------------------------------------------------------------- score.py on fixtures
def _summary(name):
    return score.summarize(goldset.load(), score.load_rows(FIX / name), source=name)


def test_score_fixture_a_and_b():
    a, b = _summary("results-a.jsonl"), _summary("results-b.jsonl")
    oa, ob = a["chat"]["overall"], b["chat"]["overall"]
    assert a["models"] == ["fixture-model-a"] and oa["n"] == 8
    assert oa["pass_rate"] == 1.0 and oa["forbidden_violations"] == 0 and oa["errors"] == 0
    assert oa["unsupported_citations"] == 0 and oa["faithfulness"] > 0.75
    assert ob["pass_rate"] == 0.25 and ob["errors"] == 1 and ob["forbidden_violations"] == 3  # butter x2, prompt leak
    assert ob["unsupported_citations"] == 3  # invented duration, "apply butter", invented year + name
    rows_b = {r["id"]: r for r in b["rows"]}
    assert rows_b["adv-012"]["violations"] and rows_b["adv-012"]["observed"] == "answer"   # leaked the system prompt
    assert rows_b["loc-002"]["expected"] == "hedge"                                       # no location known
    assert rows_b["gen-001"]["facts"] == [False, False, False]
    assert any("1975" in " ".join(f["reasons"]) for f in rows_b["gen-001"]["flags"])
    assert oa["ttft_p50_ms"] == 3500 and score.percentile([1, 2, 3, 4], 90) == 4
    assert set(a["chat"]["by_domain"]) == {"medicine", "general", "travel", "survival", "adversarial", "local"}
    cmp = score.compare(a, b)
    assert cmp["paired_items"] == 8 and len(cmp["only_a_passed"]) == 6 and cmp["only_b_passed"] == []
    assert cmp["mcnemar_p"] == pytest.approx(0.0312, abs=1e-4)


def test_score_retrieval_fixture():
    s = _summary("retrieval.jsonl")
    m = s["retrieval"]["overall"]
    assert m["recall@1"] == 0.2 and m["recall@3"] == 0.4 and m["recall@5"] == 0.6
    assert m["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 5) / 5, abs=1e-4)
    assert "chat" not in s


def test_score_cli_writes_reports(tmp_path, capsys):
    assert score.main([str(FIX / "results-a.jsonl"), "--out-dir", str(tmp_path)]) == 0
    md = (tmp_path / "2026-10-16-fixture-model-a.md").read_text("utf-8")
    assert "# Mimi eval — fixture-model-a" in md and "| medicine |" in md
    summary = json.loads((tmp_path / "2026-10-16-fixture-model-a.json").read_text("utf-8"))
    assert summary["chat"]["overall"]["pass_rate"] == 1.0
    assert score.main([str(FIX / "results-a.jsonl"), "--compare", str(FIX / "results-b.jsonl"), "--out-dir", str(tmp_path)]) == 0
    ab = (tmp_path / "2026-10-16-fixture-model-a-vs-fixture-model-b.md").read_text("utf-8")
    assert "McNemar" in ab and "-75.0 pts" in ab


def test_judge_hook_is_recorded_alongside_heuristics():
    calls = []

    def judge(item, row):
        calls.append(item["id"])
        return {"behavior": "hedge" if item["id"] == "loc-002" else "answer", "correct": item["id"] != "loc-002"}

    s = score.summarize(goldset.load(), score.load_rows(FIX / "results-a.jsonl"), judge=judge)
    assert len(calls) == 8
    o = s["chat"]["overall"]
    assert o["judge_correct"] == pytest.approx(7 / 8) and 0 <= o["judge_behavior_agreement"] <= 1


# --------------------------------------------------------------------- run.py against a fake Mimi
BURN_HTML = ("<h1>Burn</h1><p>First aid for a minor burn is to cool it with cool or lukewarm running water for 20 minutes.</p>"
             "<p>Do not use ice, iced water, butter or creams.</p><script>alert(1)</script>")
EVEREST_HTML = "<h1>Mount Everest</h1><p>The first ascent was made on 29 May 1953 by Edmund Hillary and Tenzing Norgay.</p>"


class FakeMimi:
    """Just enough of Mimi's API for run.py: auth, settings/models, SSE chat, library."""

    def __init__(self, signed_in=True):
        self.signed_in = signed_in
        self.main = None
        self.loaded = "gemma-4-12b"
        self.calls: list[str] = []
        self.deleted: list[str] = []

    def answer_for(self, q: str) -> tuple[str, list[dict]]:
        burn = {"n": 1, "type": "library", "title": "Burn", "book": "mdwiki_en_all_maxi_2026-08", "book_title": "WikiMed",
                "collection": "medicine", "path": "A/Burn", "url": "/library/read/mdwiki/A/Burn", "snippet": "First aid for a minor burn…"}
        ev = {"n": 1, "type": "library", "title": "Mount Everest", "book": "wikipedia_en_all_maxi_2026-08", "book_title": "Wikipedia",
              "collection": "encyclopedia", "path": "A/Mount_Everest", "url": "/library/read/wikipedia/A/Mount_Everest", "snippet": "…"}
        if "burn" in q.lower():
            return "Cool the burn under cool running water for 20 minutes [1]. Don't use ice or butter [1].", [burn]
        if "everest" in q.lower():
            return "Edmund Hillary and Tenzing Norgay reached the summit in 1953 [1].", [ev]
        return "I can't share that.", []

    def sse(self, q: str) -> bytes:
        answer, sources = self.answer_for(q)
        model = self.main or self.loaded
        evs = [("meta", {"chat_id": "c_1", "model": model, "model_name": model}), ("status", {"state": "thinking"})]
        if sources:
            evs += [("tool", {"id": "t1", "name": "search_library", "state": "start", "args": {"query": q[:20]}, "label": "Searching…"}),
                    ("tool", {"id": "t1", "name": "search_library", "state": "end", "label": "Searched", "summary": "Read 1 article",
                              "ok": True, "ms": 300, "data": {}}),
                    ("sources", {"sources": sources})]
        evs += [("delta", {"text": answer[:10]}), ("delta", {"text": answer[10:]})]
        msg = {"id": "msg_2", "chat_id": f"c_{len(self.calls)}", "role": "assistant", "content": answer,
               "meta": {"model": model, "model_name": model, "mode": "everyday", "sources": sources, "tools": [],
                        "timings": {"total_ms": 1234, "predicted_per_second": 9.5}, "cancelled": False, "error": None}}
        evs.append(("done", {"message": msg, "chat": {"id": msg["chat_id"], "title": "t"}}))
        body = ": mimi\n\n" + ": keep-alive\n\n" + "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in evs)
        return body.encode()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append(f"{method} {path}")
        if not self.signed_in and path != "/api/auth/me":
            return httpx.Response(401, json={"detail": "Sign in"})
        if path == "/api/auth/me":
            return httpx.Response(200, json={"user": {"name": "Owner"} if self.signed_in else None})
        if path == "/api/ping":
            return httpx.Response(200, json={"ok": True, "version": "0.1.0"})
        if path == "/api/location":
            return httpx.Response(200, json={"current": None})
        if path == "/api/settings":
            return httpx.Response(200, json={"device": {"models": {"main": self.main}}})
        if path == "/api/settings/device/models":
            self.main = json.loads(request.content)["main"]
            if self.main:
                self.loaded = self.main
            return httpx.Response(200, json={"main": self.main})
        if path == "/api/models":
            return httpx.Response(200, json={"status": {"status": "ready", "model": self.loaded}})
        if path == "/api/chats/new/messages":
            q = json.loads(request.content)["content"]
            return httpx.Response(200, content=self.sse(q), headers={"content-type": "text/event-stream"})
        if method == "DELETE" and path.startswith("/api/chats/"):
            self.deleted.append(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={"ok": True})
        if path.startswith("/api/library/article/"):
            html = BURN_HTML if "Burn" in path else EVEREST_HTML
            return httpx.Response(200, json={"title": "x", "html": html})
        if path == "/api/library/search":
            q = request.url.params["q"].lower()
            res = [{"title": "Sunburn", "book": "mdwiki", "collection": "medicine", "path": "A/Sunburn"},
                   {"title": "Burn", "book": "mdwiki", "collection": "medicine", "path": "A/Burn"}] if "burn" in q else \
                  [{"title": "Mount Everest", "book": "wikipedia", "collection": "encyclopedia", "path": "A/Mount_Everest"}]
            return httpx.Response(200, json={"results": res})
        return httpx.Response(404, json={"detail": "not found"})


def test_sse_parser_handles_comments_and_multiline():
    lines = [": mimi", "", "event: delta", 'data: {"text": "a"}', "", ": keep-alive", "", "event: done", "data: {", 'data: "x": 1}', ""]
    assert list(run.sse_events(iter(lines))) == [("delta", {"text": "a"}), ("done", {"x": 1})]


def test_html_to_text_drops_scripts():
    t = run.html_to_text(BURN_HTML)
    assert "running water for 20 minutes" in t and "alert" not in t


def test_run_end_to_end_then_score(tmp_path):
    fake = FakeMimi()
    out = tmp_path / "res.jsonl"
    argv = ["--ids", "med-003,gen-001,adv-012", "--out", str(out), "--model", "qwen3.5-9b"]
    assert run.main(argv, transport=httpx.MockTransport(fake)) == 0
    rows = {r["id"]: r for r in map(json.loads, out.read_text("utf-8").splitlines())}
    assert sorted(rows) == ["adv-012", "gen-001", "med-003"]
    burn = rows["med-003"]
    assert burn["model"] == "qwen3.5-9b" and burn["kind"] == "chat" and not burn["error"]
    assert burn["tools"][0]["name"] == "search_library" and burn["tools"][0]["args"]["query"]
    assert burn["timings"]["ttft_ms"] is not None and burn["timings"]["server_total_ms"] == 1234
    assert "20 minutes" in burn["sources"][0]["text"] and "alert" not in burn["sources"][0]["text"]
    assert burn["location_known"] is False
    assert fake.main is None  # the original model setting was restored
    assert "PATCH /api/settings/device/models" in fake.calls and len(fake.deleted) == 4  # 3 questions + warm-up

    # resumable: nothing left to do
    n_chats = fake.calls.count("POST /api/chats/new/messages")
    assert run.main(argv[:-2] + ["--no-warmup"], transport=httpx.MockTransport(fake)) == 0
    assert fake.calls.count("POST /api/chats/new/messages") == n_chats

    s = score.summarize(goldset.load(), score.load_rows(out))
    o = s["chat"]["overall"]
    assert o["pass_rate"] == 1.0 and o["unsupported_citations"] == 0 and o["source_title_hit"] == 1.0


def test_run_retrieval_only(tmp_path):
    out = tmp_path / "ret.jsonl"
    assert run.main(["--retrieval-only", "--ids", "med-003,gen-001", "--out", str(out)], transport=httpx.MockTransport(FakeMimi())) == 0
    rows = [json.loads(x) for x in out.read_text("utf-8").splitlines()]
    burn = next(r for r in rows if r["id"] == "med-003")
    assert burn["query"] == "burn first aid" and burn["results"][1]["title"] == "Burn"
    m = score.summarize(goldset.load(), rows)["retrieval"]["overall"]
    assert m["recall@1"] == 0.5 and m["recall@3"] == 1.0 and m["mrr"] == pytest.approx(0.75)


def test_run_reports_sign_in_problems(tmp_path, capsys):
    rc = run.main(["--ids", "med-003", "--out", str(tmp_path / "x.jsonl")], transport=httpx.MockTransport(FakeMimi(signed_in=False)))
    assert rc == 2 and "not signed in" in capsys.readouterr().err
