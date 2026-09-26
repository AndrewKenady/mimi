"""Hardware detection: memory, CPU, GPUs, battery → inference backend and model profile."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

from . import log
from .paths import Paths

L = log.get("hardware")

_DEV_RE = re.compile(r"^\s*(Vulkan|CUDA|ROCm|SYCL)(\d+):\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)", re.M)


def _reg(path: str, name: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip()
    except OSError:
        return None


def cpu_name() -> str:
    return (
        _reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
        or platform.processor()
        or "Unknown CPU"
    )


def device_name() -> str:
    maker = _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemManufacturer") or ""
    model = _reg(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName") or platform.node()
    return f"{maker} {model}".strip()


def list_gpu_devices(paths: Paths) -> list[dict]:
    """Ask the bundled llama.cpp builds which accelerators they can use."""
    devices: list[dict] = []
    for build in ("llama-cuda", "llama-vulkan"):
        exe = paths.exe(build, "llama-server")
        if not exe.exists():
            continue
        try:
            out = subprocess.run(
                [str(exe), "--list-devices"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            text = (out.stdout or "") + (out.stderr or "")
        except Exception as e:
            L.warning("device probe with %s failed: %s", build, e)
            continue
        for m in _DEV_RE.finditer(text):
            devices.append(
                {
                    "backend": m.group(1).lower(),
                    "index": int(m.group(2)),
                    "name": m.group(3),
                    "total_mb": int(m.group(4)),
                    "free_mb": int(m.group(5)),
                    "build": build,
                }
            )
        if devices:
            break  # prefer the first build that sees a device (CUDA before Vulkan)
    return devices


def nvidia_present() -> bool:
    return shutil.which("nvidia-smi") is not None


def battery() -> dict | None:
    try:
        b = psutil.sensors_battery()
    except Exception:
        b = None
    if b is None:
        return None
    return {
        "percent": round(b.percent),
        "plugged": bool(b.power_plugged),
        "secs_left": None if b.secsleft in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else int(b.secsleft),
    }


def pick_profile(ram_gb: float, gpus: list[dict]) -> str:
    """Map hardware to a model profile (see docs/PLAN.md §11.2)."""
    discrete_vram = max((g["total_mb"] for g in gpus if "radeon" not in g["name"].lower() or "rx" in g["name"].lower()), default=0) / 1024
    integrated = any(re.search(r"(radeon\s+\d{3}m|graphics|intel)", g["name"], re.I) for g in gpus)
    if discrete_vram >= 24 and not integrated:
        return "max"
    if ram_gb >= 48:
        return "max"
    if discrete_vram >= 16 and not integrated:
        return "plus"
    if ram_gb >= 28:
        return "plus"
    if ram_gb >= 12:
        return "standard"
    return "lite"


def detect(paths: Paths, use_cache: bool = True, max_age: float = 3600) -> dict:
    cache = paths.data / "hardware.json"
    if use_cache and cache.exists():
        try:
            info = json.loads(cache.read_text("utf-8"))
            if time.time() - info.get("detected_at", 0) < max_age:
                info["ram_available_gb"] = round(psutil.virtual_memory().available / 2**30, 1)
                info["battery"] = battery()
                return info
        except Exception:
            pass
    vm = psutil.virtual_memory()
    ram_gb = vm.total / 2**30
    gpus = list_gpu_devices(paths)
    if any(g["backend"] == "cuda" for g in gpus):
        backend = "cuda"
    elif any(g["backend"] == "vulkan" for g in gpus):
        backend = "vulkan"
    else:
        backend = "cpu"
    info = {
        "device": device_name(),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu": cpu_name(),
        "cores": psutil.cpu_count(logical=False) or 0,
        "threads": psutil.cpu_count(logical=True) or 0,
        # Physical RAM rounded up to a marketing size (the iGPU carve-out hides part of it).
        "ram_total_gb": round(ram_gb, 1),
        "ram_installed_gb": _installed_ram_gb() or round(ram_gb),
        "ram_available_gb": round(vm.available / 2**30, 1),
        "gpus": gpus,
        "backend": backend,
        "profile": pick_profile(_installed_ram_gb() or ram_gb, gpus),
        "battery": battery(),
        "detected_at": time.time(),
    }
    try:
        cache.write_text(json.dumps(info, indent=1), "utf-8")
    except OSError:
        pass
    return info


def _installed_ram_gb() -> float | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        kb = ctypes.c_ulonglong(0)
        if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)):
            return round(kb.value / 2**20, 1)
    except Exception:
        pass
    return None
