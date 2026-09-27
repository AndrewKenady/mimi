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
VALUE = "Mimi"  # the old Run entry, removed wherever it's found
TASK = "Mimi"   # Task Scheduler task that opens Mimi at sign-in
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def shell_exe(paths: Paths) -> Path:
    return paths.root / "MIMI.exe"


# Launch at sign-in is a per-user Task Scheduler task with a logon trigger, not a Run key
# entry: Explorer skipped Mimi's Run entry at sign-in on the reference device, with nothing
# logged, while running every other entry in the same key. Task Scheduler needs no admin
# rights for the user's own logon, logs every start, and ignores the battery by our settings.

def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=30)


def _task_xml(exe: Path) -> str:
    from xml.sax.saxutils import escape

    user = escape(f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\"))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Opens Mimi when you sign in to Windows (Settings, General, Launch Mimi at startup).</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(str(exe))}</Command><Arguments>--startup</Arguments><WorkingDirectory>{escape(str(exe.parent))}</WorkingDirectory></Exec></Actions>
</Task>"""


def _task_command() -> str | None:
    """The program the sign-in task starts, or None when there's no task."""
    r = _schtasks("/Query", "/TN", TASK, "/XML")
    if r.returncode != 0:
        return None
    import re

    m = re.search(r"<Command>(.*?)</Command>", r.stdout, re.S)
    from xml.sax.saxutils import unescape

    return unescape(m.group(1).strip()) if m else ""


def _remove_run_entry() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE)
            L.info("removed the old Run entry for launch at startup")
    except OSError:
        pass


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    return _task_command() is not None


def set_autostart(enabled: bool, paths: Paths) -> bool:
    """Create or remove the sign-in task for MIMI.exe (no admin rights needed)."""
    if sys.platform != "win32":
        return False
    _remove_run_entry()
    if not enabled:
        if _task_command() is not None:
            r = _schtasks("/Delete", "/TN", TASK, "/F")
            if r.returncode != 0:
                raise OSError((r.stderr or r.stdout).strip() or "schtasks /Delete failed")
        return autostart_enabled()
    exe = shell_exe(paths)
    if not exe.exists():
        raise FileNotFoundError("MIMI.exe hasn't been built yet (see shell/build.ps1).")
    import tempfile

    fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="mimi-task-")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(_task_xml(exe))
        r = _schtasks("/Create", "/TN", TASK, "/XML", xml_path, "/F")
    finally:
        os.unlink(xml_path)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout).strip() or "schtasks /Create failed")
    L.info("launch at sign-in: task %r starts %s --startup", TASK, exe)
    return autostart_enabled()


def sync_autostart(wanted: bool, paths: Paths) -> None:
    """At Core start: make the sign-in task match the setting. Moves an old Run entry over,
    and re-points the task when Mimi has moved (a portable drive with a new letter)."""
    if sys.platform != "win32":
        return
    try:
        current = _task_command()
        exe = str(shell_exe(paths))
        if wanted and (current is None or os.path.normcase(current) != os.path.normcase(exe)):
            set_autostart(True, paths)
        elif not wanted and current is not None and os.path.normcase(current) == os.path.normcase(exe):
            set_autostart(False, paths)  # another copy of Mimi elsewhere keeps its own task
        else:
            _remove_run_entry()
    except Exception as e:  # never keep Core from starting over this
        L.warning("couldn't sync launch at startup: %s", e)


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
