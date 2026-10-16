"""Child processes never outlive Mimi Core (POSIX: process groups + PR_SET_PDEATHSIG)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from mimi.procs import ManagedProcess

posix = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
CORE = Path(__file__).resolve().parents[1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie still answers kill(0); check its state where we can
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat.split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def _wait_for(pred, timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _read_pid(f: Path) -> int:
    assert _wait_for(lambda: f.exists() and f.read_text().strip().isdigit()), "child never reported its pid"
    return int(f.read_text())


@posix
def test_stop_kills_the_whole_process_group(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    code = f"import subprocess,time; p=subprocess.Popen(['sleep','300']); open({str(pidfile)!r},'w').write(str(p.pid)); time.sleep(300)"
    mp = ManagedProcess("tree", [sys.executable, "-c", code], cwd=None, log_path=tmp_path / "tree.log")
    mp.start()
    child = mp.pid
    grandchild = _read_pid(pidfile)
    assert os.getpgid(child) == child, "child should lead its own process group"
    assert os.getpgid(grandchild) == child
    mp.stop(timeout=2)
    assert not mp.alive()
    assert _wait_for(lambda: not _alive(grandchild), 5), "grandchild survived stop()"


@posix
def test_stop_escalates_to_sigkill(tmp_path):
    code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(300)"
    mp = ManagedProcess("stubborn", [sys.executable, "-c", code], cwd=None, log_path=tmp_path / "s.log")
    mp.start()
    assert _wait_for(lambda: b"ready" in (tmp_path / "s.log").read_bytes())
    pid = mp.pid
    t0 = time.time()
    mp.stop(timeout=0.5)
    assert time.time() - t0 < 5
    assert not _alive(pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux-only")
def test_children_die_when_core_is_killed(tmp_path):
    """SIGKILL the process that owns a ManagedProcess: the kernel takes the child down too."""
    pidfile = tmp_path / "engine.pid"
    fake_core = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(CORE)!r})
        from pathlib import Path
        from mimi.procs import ManagedProcess
        mp = ManagedProcess("engine", ["sleep", "300"], cwd=None, log_path=Path({str(tmp_path / 'e.log')!r}))
        mp.start()
        Path({str(pidfile)!r}).write_text(str(mp.pid))
        time.sleep(300)
    """)
    core = subprocess.Popen([sys.executable, "-c", fake_core])
    try:
        engine = _read_pid(pidfile)
        assert _alive(engine)
        core.send_signal(signal.SIGKILL)
        core.wait(timeout=5)
        assert _wait_for(lambda: not _alive(engine), 5), "engine outlived a SIGKILLed Core"
    finally:
        if core.poll() is None:
            core.kill()


def test_start_and_stop_a_quick_process(tmp_path):
    mp = ManagedProcess("echo", [sys.executable, "-c", "print('hello')"], cwd=None, log_path=tmp_path / "echo.log")
    mp.start()
    assert _wait_for(lambda: not mp.alive())
    mp.stop()
    assert "hello" in (tmp_path / "echo.log").read_text()
