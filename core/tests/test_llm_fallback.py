import asyncio
from types import SimpleNamespace

import pytest

from mimi import llm


class Spec(dict):
    id = "m"
    name = "Model"
    vision = False
    mmproj = None
    file = "m.gguf"


def _manager(ready_on: int, monkeypatch):
    m = llm.ModelManager.__new__(llm.ModelManager)
    m._switch_lock = asyncio.Lock()
    m.chat_model = m.chat_proc = None
    m.settings = SimpleNamespace(device=lambda section: SimpleNamespace(context=8192))
    m.paths = SimpleNamespace(root=".", logs=__import__("pathlib").Path("."))
    m.states = []
    m._set_state = lambda status, model=None, error=None: m.states.append(status)
    m.calls = []

    def args(spec, ctx, fit=768, cpu_only=False):
        m.calls.append((ctx, fit, cpu_only))
        return ["llama-server"]
    m._chat_args = args

    async def stop():
        pass
    m._stop_chat = stop

    async def wait_ready(proc, port, timeout):
        return len(m.calls) == ready_on
    m._wait_ready = wait_ready

    class Proc:
        def __init__(self, *a, **k): pass
        def start(self): pass
        def stop(self): pass
        def alive(self): return True
        def tail(self, n): return ""
    monkeypatch.setattr(llm, "ManagedProcess", Proc)

    class Client:
        async def get(self, *a, **k):
            raise RuntimeError("no props")
    m.client = Client()
    return m


def test_tight_graphics_memory_keeps_more_free_then_falls_back_to_cpu(monkeypatch):
    m = _manager(ready_on=4, monkeypatch=monkeypatch)
    asyncio.run(m.ensure(Spec(context=8192)))
    assert m.calls == [(8192, 768, False), (4096, 1536, False), (4096, 3072, False), (4096, 0, True)]
    assert m.states[-1] == "ready"


def test_gives_up_after_the_cpu_attempt(monkeypatch):
    m = _manager(ready_on=99, monkeypatch=monkeypatch)
    with pytest.raises(llm.ModelError):
        asyncio.run(m.ensure(Spec(context=8192)))
    assert len(m.calls) == 4 and m.states[-1] == "error"
