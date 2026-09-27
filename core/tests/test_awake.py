import sys

import pytest

from mimi import awake


@pytest.mark.skipif(sys.platform != "win32", reason="Windows power requests")
def test_holds_and_releases(monkeypatch):
    monkeypatch.setattr(awake, "RECHECK", 0.05)
    calls = []

    class K32:
        @staticmethod
        def SetThreadExecutionState(flags):
            calls.append(flags)
            return 1

    import ctypes
    monkeypatch.setattr(ctypes.windll, "kernel32", K32)
    want = {"v": True}
    k = awake.KeepAwake(lambda: want["v"])
    k.start()
    import time
    for _ in range(40):
        if k.holding:
            break
        time.sleep(0.02)
    assert k.holding and calls[-1] == awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED
    want["v"] = False
    for _ in range(40):
        if not k.holding:
            break
        time.sleep(0.02)
    assert not k.holding and calls[-1] == awake.ES_CONTINUOUS
    want["v"] = True
    time.sleep(0.2)
    k.stop()
    assert calls[-1] == awake.ES_CONTINUOUS  # released on the way out
