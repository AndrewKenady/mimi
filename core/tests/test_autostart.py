import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mimi import system

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows sign-in task")


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    """A stand-in Task Scheduler: one task slot, recording every schtasks call."""
    state = {"task": None, "calls": [], "run_removed": 0}
    exe = tmp_path / "MIMI.exe"
    exe.write_bytes(b"")

    def schtasks(*args):
        state["calls"].append(args[0])
        if args[0] == "/Query":
            if state["task"] is None:
                return subprocess.CompletedProcess(args, 1, "", "ERROR: not found")
            return subprocess.CompletedProcess(args, 0, f"<Task><Command>{state['task']}</Command></Task>", "")
        if args[0] == "/Create":
            xml = Path(args[args.index("/XML") + 1]).read_text("utf-16")
            state["xml"] = xml
            state["task"] = xml.split("<Command>")[1].split("</Command>")[0]
            return subprocess.CompletedProcess(args, 0, "SUCCESS", "")
        if args[0] == "/Delete":
            state["task"] = None
            return subprocess.CompletedProcess(args, 0, "SUCCESS", "")
        raise AssertionError(args)

    monkeypatch.setattr(system, "_schtasks", schtasks)
    monkeypatch.setattr(system, "_remove_run_entry", lambda: state.__setitem__("run_removed", state["run_removed"] + 1))
    state["paths"] = SimpleNamespace(root=tmp_path)
    return state


def test_turning_on_creates_a_logon_task_and_drops_the_run_entry(fake):
    assert system.set_autostart(True, fake["paths"]) is True
    xml = fake["xml"]
    assert "<LogonTrigger>" in xml and "<Arguments>--startup</Arguments>" in xml
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml and "<Priority>4</Priority>" in xml
    assert fake["run_removed"] == 1


def test_turning_off_deletes_the_task(fake):
    system.set_autostart(True, fake["paths"])
    assert system.set_autostart(False, fake["paths"]) is False
    assert fake["task"] is None


def test_sync_moves_an_old_setting_over_and_follows_a_moved_folder(fake, tmp_path):
    system.sync_autostart(True, fake["paths"])             # setting on, no task yet
    assert fake["task"] == str(tmp_path / "MIMI.exe")
    fake["task"] = r"E:\Mimi\MIMI.exe"                        # the drive came back as another letter
    system.sync_autostart(True, fake["paths"])
    assert fake["task"] == str(tmp_path / "MIMI.exe")
    calls = len(fake["calls"])
    system.sync_autostart(True, fake["paths"])             # already right: nothing rewritten
    assert fake["calls"][calls:] == ["/Query"]


def test_sync_leaves_another_copys_task_alone(fake):
    fake["task"] = r"E:\Mimi\MIMI.exe"
    system.sync_autostart(False, fake["paths"])
    assert fake["task"] == r"E:\Mimi\MIMI.exe"


def test_sync_never_raises(fake, monkeypatch):
    monkeypatch.setattr(system, "_schtasks", lambda *a: (_ for _ in ()).throw(OSError("no schtasks")))
    system.sync_autostart(True, fake["paths"])  # logged, not raised
