"""Child-process management for bundled native services (llama-server, kiwix-serve).

On Windows every child is placed in a Job Object with KILL_ON_JOB_CLOSE, so if
MIMI Core exits or crashes, its children die with it — no orphaned servers
holding GPU memory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import log

L = log.get("procs")

_job_handle = None
_job_lock = threading.Lock()


def _job():
    """Lazily create a process-wide Job Object (Windows only)."""
    global _job_handle
    if sys.platform != "win32":
        return None
    with _job_lock:
        if _job_handle is not None:
            return _job_handle
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        h = k32.CreateJobObjectW(None, None)
        if not h:
            return None
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info))
        _job_handle = (k32, h)
        return _job_handle


def _assign_to_job(proc: subprocess.Popen) -> None:
    j = _job()
    if not j:
        return
    k32, h = j
    try:
        k32.AssignProcessToJobObject(h, int(proc._handle))  # type: ignore[attr-defined]
    except Exception as e:  # pragma: no cover - best effort
        L.warning("could not assign pid %s to job: %s", proc.pid, e)


class ManagedProcess:
    def __init__(self, name: str, args: list[str], cwd: Path | None, log_path: Path, env: dict | None = None):
        self.name = name
        self.args = [str(a) for a in args]
        self.cwd = cwd
        self.log_path = log_path
        self.env = env
        self.proc: subprocess.Popen | None = None
        self.started_at: float | None = None
        self._logf = None

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.alive():
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logf = open(self.log_path, "ab", buffering=0)
        self._logf.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} starting: {' '.join(self.args)}\n".encode())
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        env = dict(os.environ)
        if self.env:
            env.update(self.env)
        self.proc = subprocess.Popen(
            self.args,
            cwd=str(self.cwd) if self.cwd else None,
            stdout=self._logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=flags,
        )
        _assign_to_job(self.proc)
        self.started_at = time.time()
        L.info("%s started (pid %s)", self.name, self.proc.pid)

    def stop(self, timeout: float = 5.0) -> None:
        p = self.proc
        if p is None:
            return
        if p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass
        L.info("%s stopped", self.name)
        self.proc = None
        if self._logf:
            try:
                self._logf.close()
            except Exception:
                pass
            self._logf = None

    def tail(self, n: int = 40) -> str:
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 16000))
                return b"\n".join(f.read().splitlines()[-n:]).decode("utf-8", "replace")
        except OSError:
            return ""
