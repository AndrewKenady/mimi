"""Device integration: launch at startup, disk usage, open folders."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import log
from .paths import Paths

L = log.get("system")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "Mimi"


def shell_exe(paths: Paths) -> Path:
    return paths.root / "MIMI.exe"


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool, paths: Paths) -> bool:
    """Per-user Run entry pointing at MIMI.exe (no admin rights needed)."""
    if sys.platform != "win32":
        return False
    import winreg

    exe = shell_exe(paths)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            if not exe.exists():
                raise FileNotFoundError("MIMI.exe hasn't been built yet (see shell/build.ps1).")
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, f'"{exe}" --startup')
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except OSError:
                pass
    return autostart_enabled()


_usage_cache: dict = {"at": 0.0, "data": None}
_usage_lock = threading.Lock()


def _dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def disk_usage(paths: Paths, max_age: float = 600) -> dict:
    with _usage_lock:
        if _usage_cache["data"] and time.time() - _usage_cache["at"] < max_age:
            return _usage_cache["data"]
        parts = {
            "Offline library": paths.zim,
            "AI models": paths.models,
            "Maps": paths.maps,
            "Your data": paths.data,
            "Runtimes": paths.root / "python",
            "Engines": paths.root / "bin",
            "App": paths.root / "ui" / "build",
        }
        items = [{"label": k, "bytes": _dir_size(v)} for k, v in parts.items()]
        du = shutil.disk_usage(paths.root)
        data = {"items": items, "drive": {"total": du.total, "used": du.used, "free": du.free, "root": str(paths.root.anchor)}}
        _usage_cache.update(at=time.time(), data=data)
        return data


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
