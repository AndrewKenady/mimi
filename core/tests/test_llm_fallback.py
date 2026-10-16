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


def test_apple_silicon_offloads_to_metal_and_the_cpu_retry_does_not(tmp_path):
    bin_dir = tmp_path / "bin" / "macos-arm64"
    for b in ("llama-metal", "llama-cpu"):
        (bin_dir / b).mkdir(parents=True)
        (bin_dir / b / "llama-server").write_text("")
    m = llm.ModelManager.__new__(llm.ModelManager)
    m.hw = {"backend": "metal", "cores": 8}
    m.paths = SimpleNamespace(exe=lambda *parts: bin_dir.joinpath(*parts))

    gpu = m._chat_args(Spec(), 8192)
    assert gpu[0] == str(bin_dir / "llama-metal" / "llama-server")
    assert "-ngl" not in gpu and gpu[gpu.index("--fit") + 1] == "on"

    cpu = m._chat_args(Spec(), 4096, 0, cpu_only=True)
    assert cpu[0] == str(bin_dir / "llama-cpu" / "llama-server")
    assert cpu[cpu.index("-ngl") + 1] == "0"


def test_cpu_retry_stays_on_the_cpu_when_only_the_metal_build_is_installed(tmp_path):
    (tmp_path / "llama-metal").mkdir()
    (tmp_path / "llama-metal" / "llama-server").write_text("")
    m = llm.ModelManager.__new__(llm.ModelManager)
    m.hw = {"backend": "cpu", "cores": 8}
    m.paths = SimpleNamespace(exe=lambda *parts: tmp_path.joinpath(*parts))
    assert m._build_dir() == "llama-metal"
    args = m._chat_args(Spec(), 4096, 0, cpu_only=True)
    assert args[args.index("-ngl") + 1] == "0"
