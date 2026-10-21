"""The chat llama-server's command line: its prompt cache in RAM is sized to the device."""

from types import SimpleNamespace

import pytest

from mimi import llm


class Spec(dict):
    id = "m"
    name = "Model"
    vision = False
    mmproj = None
    file = "m.gguf"


class Exe:
    def __init__(self, build):
        self.build = build

    def exists(self):
        return self.build == "llama-vulkan"

    def __str__(self):
        return f"bin/{self.build}/llama-server"


def _cache_ram(hw: dict) -> str:
    m = llm.ModelManager.__new__(llm.ModelManager)
    m.hw = {"backend": "vulkan", "cores": 8, **hw}
    m.paths = SimpleNamespace(exe=lambda build, name: Exe(build))
    args = m._chat_args(Spec(), 8192)
    return args[args.index("--cache-ram") + 1]


@pytest.mark.parametrize("hw, mib", [
    ({"ram_installed_gb": 16, "ram_total_gb": 12.8}, "512"),  # the F1: 16 GB, about 3 GB of it reserved for graphics
    ({"ram_installed_gb": 32}, "2048"),
    ({"ram_installed_gb": 64}, "8192"),                      # llama.cpp's own default
    ({}, "512"),                                             # unknown hardware: assume the small device
])
def test_prompt_cache_in_ram_fits_the_device(hw, mib):
    assert _cache_ram(hw) == mib


def test_the_kv_cache_is_quantized_on_both_halves():
    """An f16 V cache ran gemma-4-12b out of graphics memory on long prompts at an 8192 context on the F1."""
    m = llm.ModelManager.__new__(llm.ModelManager)
    m.hw = {"backend": "vulkan", "cores": 8, "ram_installed_gb": 16}
    m.paths = SimpleNamespace(exe=lambda build, name: Exe(build))
    args = m._chat_args(Spec(), 8192)
    assert args[args.index("-ctk") + 1] == "q8_0" and args[args.index("-ctv") + 1] == "q8_0"
