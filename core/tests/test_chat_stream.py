"""The chat turn's event stream: sources first, a verbatim preview, an honest progress narrative.

The model and the library are faked so the whole turn loop runs in milliseconds.
"""

import asyncio
from types import SimpleNamespace

import pytest

from mimi.kiwix import Hit, Passage
from mimi.llm import ModelError

HYPO = (
    "Hypothermia is defined as a body core temperature below 35.0 °C in humans. Symptoms depend on the temperature.\n"
    "## Signs and symptoms\n"
    "In mild hypothermia there is shivering and mental confusion. In moderate hypothermia shivering stops and confusion increases.\n"
    "## Management\n"
    "Treatment of mild hypothermia involves warm drinks, warm clothing, and voluntary physical activity. "
    "In those with moderate hypothermia, heating blankets and warmed intravenous fluids are recommended. "
    "People with severe hypothermia may benefit from extracorporeal membrane oxygenation or cardiopulmonary bypass."
)
FROSTBITE = "Frostbite is a skin injury that occurs when exposed to extreme low temperatures, most commonly in the hands and feet."


class Spec(dict):
    id = "gemma"
    name = "Gemma"
    vision = False


class FakeModels:
    """Plays back one scripted step per chat_stream call."""

    def __init__(self, steps, spec=Spec(context=8192)):
        self.steps = list(steps)
        self.spec = spec
        self.gen_lock = asyncio.Lock()
        self.waiting = 0
        self.chat_model = spec
        self.chat_proc = SimpleNamespace(alive=lambda: True)
        self.chat_ctx = 8192
        self.prompts = []

    def model_for(self, role):
        return self.spec

    async def ensure(self, spec):
        pass

    async def chat_stream(self, spec, messages, **kw):
        self.prompts.append(list(messages))
        step = self.steps.pop(0) if self.steps else {"text": "…"}
        if step.get("raise"):
            raise ModelError(step["raise"])
        for piece in step.get("text_pieces") or ([step["text"]] if step.get("text") else []):
            yield {"type": "content", "text": piece}
        if step.get("calls"):
            yield {"type": "tool_calls", "calls": step["calls"]}
        yield {"type": "done", "timings": step.get("timings") or {}}

    async def chat_once(self, *a, **k):
        return "Hypothermia care"


class FakeKiwix:
    async def books(self, include_disabled=False):
        return [SimpleNamespace(collection="medicine", name="wikimed", title="WikiMed"),
                SimpleNamespace(collection="encyclopedia", name="wikipedia", title="Wikipedia")]

    async def search(self, q, collections=None, books=None, limit=5):
        return [Hit(title="Hypothermia", path="A/Hypothermia", book="wikimed", book_title="WikiMed Medical Encyclopedia", collection="medicine", snippet=""),
                Hit(title="Frostbite", path="A/Frostbite", book="wikipedia", book_title="Wikipedia", collection="encyclopedia", snippet="")]

    async def passage(self, hit, q, chars):
        text = HYPO if hit.title == "Hypothermia" else FROSTBITE
        return Passage(title=hit.title, book=hit.book, book_title=hit.book_title, collection=hit.collection, path=hit.path,
                       text=text, image="/kiwix/wikimed/I/hypo.jpg" if hit.title == "Hypothermia" else None,
                       url=f"/library/read/{hit.book}/{hit.path}")


SEARCH = {"calls": [{"id": "t1", "name": "search_library", "arguments": '{"query": "hypothermia treatment"}'}],
          "timings": {"prompt_n": 40, "prompt_per_second": 60}}
ANSWER = {"text_pieces": ["Warm the person ", "slowly [1]."], "timings": {"prompt_n": 900, "prompt_per_second": 110, "predicted_n": 6, "predicted_per_second": 8.1}}


@pytest.fixture()
def svc(client):
    from mimi.auth import Ctx

    client.post("/api/auth/setup", json={"name": "Ada"})
    s = client.app.state.svc
    s.kiwix = FakeKiwix()
    s.kiwix_service.alive = lambda: True
    s.ctx = Ctx(dict(s.auth.list()[0]), None, True)
    return s


def run_turn(svc, steps, chat_id=None, **kw):
    svc.models = FakeModels(steps)

    async def go():
        return [ev async for ev in svc.chats.send(svc.ctx, chat_id, **kw)]

    return asyncio.run(go())


def test_sources_and_preview_arrive_before_the_answer(svc):
    evs = run_turn(svc, [SEARCH, ANSWER], content="How do you treat hypothermia?", mode="everyday")
    names = [e["event"] for e in evs]
    first_delta = names.index("delta")
    assert names.index("sources") < names.index("preview") < first_delta
    assert names[-1] == "done"

    statuses = [e["data"] for e in evs if e["event"] == "status"]
    assert [s["state"] for s in statuses] == ["thinking", "searching", "reading", "writing"]
    assert all("elapsed_ms" in s for s in statuses)
    assert [s["elapsed_ms"] for s in statuses] == sorted(s["elapsed_ms"] for s in statuses)
    searching, reading = statuses[1], statuses[2]
    assert searching["label"] == "Searching Wikipedia and WikiMed for “hypothermia treatment”…" and searching["tool"] == "search_library"
    assert reading["label"] == "Reading “Hypothermia” (WikiMed) and 1 more…"
    assert reading["sources"] == 2 and reading["prompt_tokens"] > 50
    # no measured speed yet (the step-0 prompt was too short to trust), so no made-up estimate
    assert "eta_ms" not in reading

    tool_start = next(e["data"] for e in evs if e["event"] == "tool" and e["data"]["state"] == "start")
    assert tool_start["label"] == searching["label"]  # the activity trail and the narrative agree

    preview = next(e["data"] for e in evs if e["event"] == "preview")
    assert preview["n"] == 1 and preview["title"] == "Hypothermia" and preview["collection"] == "medicine"
    assert preview["section"] == "Management" and preview["text"].startswith("Treatment of mild hypothermia")
    assert len(preview["text"]) <= 420 and preview["text"] in HYPO  # verbatim, whole sentences
    assert preview["image"] and preview["url"].startswith("/library/read/")

    done = evs[-1]["data"]["message"]
    assert done["content"] == "Warm the person slowly [1]."
    assert done["meta"]["preview"] == preview and len(done["meta"]["sources"]) == 2


def test_reading_estimate_uses_this_devices_measured_speed(svc):
    run_turn(svc, [SEARCH, ANSWER], content="How do you treat hypothermia?")  # stores timings: 900 tokens at 110 t/s
    svc.chats._prompt_tps.clear()  # a restart: the speed is re-learned from stored answers
    evs = run_turn(svc, [SEARCH, ANSWER], content="What about frostbite?")
    reading = next(e["data"] for e in evs if e["event"] == "status" and e["data"]["state"] == "reading")
    assert reading["eta_ms"] == int(reading["prompt_tokens"] / 110 * 1000)


def test_chitchat_streams_without_tools_or_preview(svc):
    evs = run_turn(svc, [{"text": "Hi Ada!"}], content="hello")
    names = [e["event"] for e in evs]
    assert "preview" not in names and "sources" not in names
    assert [e["data"]["state"] for e in evs if e["event"] == "status"] == ["thinking", "writing"]
    assert "preview" not in evs[-1]["data"]["message"]["meta"]


def test_failed_turn_can_be_retried_from_the_user_message(svc):
    evs = run_turn(svc, [{"raise": "The model stopped responding."}], content="How do you treat hypothermia?")
    err = next(e["data"] for e in evs if e["event"] == "error")
    failed = evs[-1]["data"]["message"]
    assert err["message_id"] == failed["id"] and failed["content"] == "" and failed["meta"]["error"]
    chat_id = evs[0]["data"]["chat_id"]
    user_id = evs[0]["data"]["user_message"]["id"]

    # Retry by user message id: answers the same question, no duplicate user message.
    evs = run_turn(svc, [SEARCH, ANSWER], chat_id=chat_id, content="", regenerate=user_id)
    assert evs[0]["data"]["user_message"]["id"] == user_id
    final = evs[-1]["data"]["message"]
    assert final["content"].startswith("Warm") and final["parent_id"] == user_id
    assert final["versions"]["count"] == 2  # the failed attempt stays as version 1
    thread = svc.chats.get_full(svc.ctx, chat_id)["messages"]
    assert [m["role"] for m in thread] == ["user", "assistant"]


def test_stop_keeps_partial_content(svc):
    class Stopping(FakeModels):
        async def chat_stream(self, spec, messages, cancel=None, **kw):
            yield {"type": "content", "text": "Partial "}
            svc.chats.stop(chat_id[0])
            yield {"type": "content", "text": "answer"}
            yield {"type": "done", "timings": {}}

    chat_id = [svc.chats.create(svc.ctx)["id"]]
    svc.models = Stopping([])

    async def go():
        return [ev async for ev in svc.chats.send(svc.ctx, chat_id[0], content="Tell me a story")]

    evs = asyncio.run(go())
    final = evs[-1]["data"]["message"]
    assert final["meta"]["cancelled"] is True and final["content"] == "Partial answer"


def test_tool_passages_and_best_excerpt():
    from mimi.chat import best_excerpt, tool_passages

    text = f"[1] Hypothermia — WikiMed\n{HYPO}\n\n[2] Frostbite — Wikipedia\n{FROSTBITE}\n\nCite these as [n]."
    p = tool_passages(text)
    assert set(p) == {1, 2} and p[2] == FROSTBITE and "## Management" in p[1]

    excerpt, section = best_excerpt(p[1], "how to treat hypothermia", "Hypothermia", max_chars=150)
    assert section == "Management" and excerpt == (
        "Treatment of mild hypothermia involves warm drinks, warm clothing, and voluntary physical activity.")
    # no query terms in the passage: fall back to the lead paragraph
    excerpt, section = best_excerpt(p[1], "zzz", "Hypothermia")
    assert section is None and excerpt.startswith("Hypothermia is defined")
    assert best_excerpt("", "x") == ("", None)
