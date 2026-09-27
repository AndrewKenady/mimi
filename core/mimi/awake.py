"""Keep the computer from going to sleep while Mimi runs.

Phones and laptops on the network reach Mimi through this machine, and a download or a
long answer shouldn't die because Windows decided the machine was idle. The screen may
still turn off on its usual timer; only system sleep is held off. Closing the lid or
pressing the power button still sleeps as normal.

Windows ties the request to the thread that made it, so one small thread owns it for as
long as it's wanted and clears it before exiting.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

L = logging.getLogger("mimi.awake")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
RECHECK = 30.0  # seconds between looks at the setting


class KeepAwake:
    def __init__(self, wanted: Callable[[], bool]) -> None:
        self._wanted = wanted
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.holding = False

    @staticmethod
    def supported() -> bool:
        return sys.platform == "win32"

    def start(self) -> None:
        if not self.supported() or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="mimi-keep-awake", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _set(self, hold: bool) -> None:
        import ctypes

        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if hold else 0)
        if ctypes.windll.kernel32.SetThreadExecutionState(flags) == 0:
            L.warning("SetThreadExecutionState refused %#x", flags)
            return
        if hold != self.holding:
            L.info("keeping the computer awake" if hold else "letting the computer sleep normally")
        self.holding = hold

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    want = bool(self._wanted())
                except Exception as e:  # a settings hiccup shouldn't flip the machine to sleep
                    L.debug("keep-awake setting unreadable: %s", e)
                    want = self.holding
                if want != self.holding:
                    self._set(want)
                self._stop.wait(RECHECK)
        finally:
            if self.holding:
                self._set(False)
