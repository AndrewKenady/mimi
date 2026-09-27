"""In-process event bus that fans events out to WebSocket clients.

Publishing is thread-safe: worker threads (transcription, indexing, GPS) call
`publish()`, which hops onto the event loop.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(eq=False)
class Subscriber:
    user_id: str | None
    role: str
    local: bool = False  # connected from the device's own screen (loopback app port)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=500))


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.last: dict[str, dict] = {}  # last event per type (for late subscribers)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, user_id: str | None, role: str, local: bool = False) -> Subscriber:
        s = Subscriber(user_id, role, local)
        self._subs.add(s)
        return s

    def unsubscribe(self, s: Subscriber) -> None:
        self._subs.discard(s)

    def watching(self, user_id: str, *, local: bool = False) -> bool:
        """Whether this user has a live window open (on the device's own screen, with local=True)."""
        return any(s.user_id == user_id and (s.local or not local) for s in list(self._subs))

    def publish(self, type_: str, data: Any = None, *, user_id: str | None = None, owner_only: bool = False, sticky: bool = False) -> None:
        event = {"type": type_, "data": data, "ts": time.time()}
        if sticky:
            self.last[type_] = event
        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._deliver(event, user_id, owner_only)
        else:
            loop.call_soon_threadsafe(self._deliver, event, user_id, owner_only)

    def _deliver(self, event: dict, user_id: str | None, owner_only: bool) -> None:
        for s in list(self._subs):
            if user_id is not None and s.user_id != user_id:
                continue
            if owner_only and s.role != "owner":
                continue
            try:
                s.queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow client: drop rather than block everyone
