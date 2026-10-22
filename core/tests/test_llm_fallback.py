import asyncio
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from mimi import llm

OOM = "ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory"


class Spec(dict):
    id = "m"
    name = "Model"
    vision = False
    mmproj = None
    file = "m.gguf"


def _manager(ready_on: int | None, monkeypatch):
    """A ModelManager whose llama-servers are fakes; with ready_on=None every start succeeds."""
    m = llm.ModelManager.__new__(llm.ModelManager)
    m._switch_lock = asyncio.Lock()
    m.chat_model = m.chat_proc = None
    m.chat_attempt, m._chat_ladder = 0, (0, [])
    m._resume = {}
    m.context = 8192
    m.settings = SimpleNamespace(device=lambda section: SimpleNamespace(context=m.context, temperature=None))
    m.paths = SimpleNamespace(root=".", logs=__import__("pathlib").Path("."))
    m.states = []
    m._set_state = lambda status, model=None, error=None: m.states.append(status)
    m.calls = []
    m.procs = []

    def args(spec, ctx, fit=768, cpu_only=False, v_cache="f16"):
        m.calls.append((ctx, fit, cpu_only) if v_cache == "f16" else (ctx, fit, cpu_only, v_cache))
        return ["llama-server"]
    m._chat_args = args

    async def wait_ready(proc, port, timeout):
        return ready_on is None or len(m.calls) == ready_on
    m._wait_ready = wait_ready

    class Proc:
        def __init__(self, *a, **k):
            self.dead = False
            m.procs.append(self)
        def start(self): pass
        def stop(self): self.dead = True
        def alive(self): return not self.dead
        def tail(self, n): return OOM
    monkeypatch.setattr(llm, "ManagedProcess", Proc)

    class Client:
        async def get(self, *a, **k):
            raise RuntimeError("no props")
    m.client = Client()
    return m


def test_tight_graphics_memory_keeps_more_free_then_falls_back_to_cpu(monkeypatch):
    m = _manager(ready_on=5, monkeypatch=monkeypatch)
    asyncio.run(m.ensure(Spec(context=8192)))
    # a q8_0 V cache before more memory left free: on the F1 that kept the generation speed (7.8 instead of 4.6
    # tokens/s), while each request took about 3 s longer to start
    assert m.calls == [(8192, 768, False), (4096, 1536, False), (4096, 1536, False, "q8_0"), (4096, 3072, False), (4096, 0, True)]
    assert m.states[-1] == "ready"


def test_gives_up_after_the_cpu_attempt(monkeypatch):
    m = _manager(ready_on=99, monkeypatch=monkeypatch)
    with pytest.raises(llm.ModelError):
        asyncio.run(m.ensure(Spec(context=8192)))
    assert len(m.calls) == 5 and m.states[-1] == "error"


def _crash(m):
    """The resident llama-server runs out of graphics memory on a prompt and exits."""
    m.procs[-1].dead = True


def _server(m, crash_first: int = 0) -> httpx.AsyncClient:
    """llama-server's chat endpoint. The first `crash_first` requests take the resident process down."""
    crashes = [crash_first]

    def handle(request):
        if request.url.path != "/v1/chat/completions":
            return httpx.Response(404)
        if crashes[0]:
            crashes[0] -= 1
            _crash(m)
            raise httpx.ReadError("connection closed", request=request)
        if json.loads(request.content)["stream"]:
            chunk = {"choices": [{"delta": {"content": "Hello!"}, "finish_reason": "stop"}]}
            return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hello!"}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "mimi.llm" and r.levelno == logging.WARNING]


def test_a_model_that_crashes_after_loading_restarts_one_rung_down(monkeypatch, caplog):
    """gemma-4-12b on a 16 GB handheld: loads fine, then runs out of graphics memory on its first prompt.
    Starting it again with the same settings would crash it again, forever."""
    m = _manager(None, monkeypatch)
    spec = Spec(context=8192)

    async def go():
        await m.ensure(spec)
        for _ in range(5):
            _crash(m)
            await m.ensure(spec)

    with caplog.at_level(logging.WARNING, logger="mimi.llm"):
        asyncio.run(go())
    assert m.calls == [(8192, 768, False), (4096, 1536, False), (4096, 1536, False, "q8_0"), (4096, 3072, False),
                       (4096, 0, True), (4096, 0, True)]  # CPU only is as far down as it goes
    assert m.states[-1] == "ready" and m.chat_attempt == 4
    assert "it restarts with ctx 4096, 1536 MB graphics memory kept free, q8_0 V cache" in _warnings(caplog)[1]
    first = _warnings(caplog)[0]
    assert "m exited unexpectedly with ctx 8192, 768 MB graphics memory kept free (attempt 1)" in first
    assert "it restarts with ctx 4096, 1536 MB graphics memory kept free" in first and OOM in first


def test_a_model_up_but_out_of_graphics_memory_restarts_one_rung_down(monkeypatch, caplog):
    """On the F1, other programs took graphics memory after gemma loaded: llama-server stayed up, failed every
    request with an error inside the stream, and turns ended with nothing written."""
    m = _manager(None, monkeypatch)
    oom = {"error": {"code": 500, "message": "decode() failed: vk::Device::allocateMemory: ErrorOutOfDeviceMemory",
                     "type": "server_error"}}
    m.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=f"data: {json.dumps(oom)}\n\n")))
    spec = Spec(context=8192)

    async def go():
        await m.ensure(spec)
        with pytest.raises(llm.ModelOutOfMemory) as e:
            async for _ in m.chat_stream(spec, [{"role": "user", "content": "hi"}]):
                pass
        assert await m.died_during(e.value)
        assert m._resume == {"m": (8192, 1)} and m.procs[0].dead  # stopped, to start one rung down
        await m.ensure(spec)

    with caplog.at_level(logging.WARNING, logger="mimi.llm"):
        asyncio.run(go())
    assert m.calls == [(8192, 768, False), (4096, 1536, False)]
    assert "m ran out of graphics memory with ctx 8192, 768 MB graphics memory kept free" in _warnings(caplog)[0]
    assert not isinstance(llm._model_error("500: something else"), llm.ModelOutOfMemory)
    # what the next request got on the F1 after a decode had run out of memory
    assert isinstance(llm._model_error('500: {"error":{"message":"Invalid input batch."}}'), llm.ModelOutOfMemory)


def test_a_crash_between_turns_is_noticed_once(monkeypatch, caplog):
    m = _manager(None, monkeypatch)
    asyncio.run(m.ensure(Spec(context=8192)))
    assert m.crashed() is False
    _crash(m)
    with caplog.at_level(logging.WARNING, logger="mimi.llm"):
        assert m.crashed() and m.crashed()  # the janitor's look, then a turn's
    assert len(_warnings(caplog)) == 1
    assert m.states[-1] == "error" and m.chat_model is None and m._resume == {"m": (8192, 1)}


def test_full_settings_get_another_chance_once_the_lighter_ones_have_answered(monkeypatch):
    m = _manager(None, monkeypatch)
    m.client = _server(m)
    spec = Spec(context=8192)

    async def go():
        await m.ensure(spec)
        _crash(m)
        await m.ensure(spec)  # lighter settings
        await m._stop_chat()  # swapped out (for the vision model, say) before it answered anything
        await m.ensure(spec)  # still the lighter settings: nothing says the full ones would fare better
        assert await m.chat_once(spec, [{"role": "user", "content": "hi"}]) == "Hello!"
        await m._stop_chat()
        await m.ensure(spec)  # it answered, and memory pressure passes: a fresh start tries the full settings

    asyncio.run(go())
    assert m.calls == [(8192, 768, False), (4096, 1536, False), (4096, 1536, False), (8192, 768, False)]


def test_a_settings_change_or_restart_starts_from_the_top(monkeypatch):
    m = _manager(None, monkeypatch)
    spec = Spec(context=8192)

    async def go():
        await m.ensure(spec)
        _crash(m)
        m.context = 4096  # a smaller context picked in Settings: a different ladder
        await m.ensure(spec)
        _crash(m)
        assert m.crashed() and m._resume == {"m": (4096, 1)}
        await m.unload()  # Settings reloads the model; so does Restart services
        await m.ensure(spec)

    asyncio.run(go())
    assert m.calls == [(8192, 768, False), (4096, 768, False), (4096, 768, False)]


def test_a_dropped_connection_waits_for_the_process_to_exit(monkeypatch):
    m = _manager(None, monkeypatch)

    async def go():
        await m.ensure(Spec(context=8192))
        assert await m.died_during(llm.ModelError("model error 400: context too long")) is False  # still running
        checks = iter([True, True])  # the socket closes a moment before the process is gone
        m.procs[-1].alive = lambda: next(checks, False)
        assert await m.died_during(httpx.ReadError("connection closed")) is True
        assert m._resume == {"m": (8192, 1)}

    asyncio.run(go())


def test_a_stream_that_takes_the_model_down_restarts_it_one_rung_down(monkeypatch):
    m = _manager(None, monkeypatch)
    m.client = _server(m, crash_first=1)
    spec = Spec(context=8192)
    prompt = [{"role": "user", "content": "hi"}]

    async def go():
        with pytest.raises(httpx.ReadError) as e:
            [ev async for ev in m.chat_stream(spec, prompt)]
        assert await m.died_during(e.value)
        return [ev async for ev in m.chat_stream(spec, prompt)]

    evs = asyncio.run(go())
    assert m.calls == [(8192, 768, False), (4096, 1536, False)]
    assert evs[0] == {"type": "content", "text": "Hello!"} and evs[-1]["type"] == "done"
    assert m._resume == {}  # it answered


@pytest.mark.parametrize("backend, installed, expected", [
    ("metal", {"llama-metal", "llama-cpu"}, "llama-metal"),   # Apple silicon uses the GPU build
    ("metal", {"llama-cpu"}, "llama-cpu"),                    # ...and still runs without it
    ("cuda", {"llama-vulkan", "llama-cpu"}, "llama-vulkan"),
    ("cpu", {"llama-metal", "llama-cpu"}, "llama-cpu"),
])
def test_build_dir_follows_the_detected_backend(tmp_path, backend, installed, expected):
    m = llm.ModelManager.__new__(llm.ModelManager)
    m.hw = {"backend": backend}
    m.paths = SimpleNamespace(exe=lambda build, name: tmp_path / build / name)
    for b in installed:
        (tmp_path / b).mkdir()
        (tmp_path / b / "llama-server").write_text("")
    assert m._build_dir() == expected
    assert m._build_dir(cpu_only=True) == "llama-cpu"
