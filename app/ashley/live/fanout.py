"""One process's open screens: each a bounded queue that drops its oldest event rather than hold up whoever delivers,
so a slow screen never slows the feed. Pure and in-process; a `Live` implementation feeds it.

Logs `live.closed` per subscription with the person id (or device id), events sent, events dropped and duration_ms."""

import asyncio
import logging
import time
from collections import deque
from types import TracebackType

from .. import logs
from .events import DeviceViewer, Event, Watcher, shown_to

log = logging.getLogger("ashley.live")


class Resync:
    """Something may have been missed (the feed reconnected, or this screen fell behind): refetch what is shown."""


RESYNC = Resync()


class Subscription:
    """One open screen's events, in order. An async context manager: it is fed only between entering and leaving."""

    def __init__(self, fanout: "Fanout", viewer: Watcher, size: int) -> None:
        self.viewer = viewer
        self._fanout = fanout
        self._queue: deque[Event | Resync] = deque()
        self._size = size
        self._wake = asyncio.Event()
        self._sent = 0
        self._dropped = 0
        self._opened = time.perf_counter()

    async def __aenter__(self) -> "Subscription":
        self._fanout.add(self)
        return self

    async def __aexit__(self, kind: type[BaseException] | None, exc: BaseException | None,
                        tb: TracebackType | None) -> None:
        self._fanout.remove(self)
        v = self.viewer
        who = {"device": v.device_id} if isinstance(v, DeviceViewer) else {"person": v.person_id}
        logs.info(log, "live.closed", **who, sent=self._sent, dropped=self._dropped,
                  duration_ms=int((time.perf_counter() - self._opened) * 1000))

    def offer(self, item: Event | Resync) -> None:
        """Queue `item`. When the queue is full, everything waiting is dropped for one resync, since a screen that fell
        behind refetches anyway."""
        if len(self._queue) >= self._size:
            self._dropped += sum(1 for waiting in self._queue if not isinstance(waiting, Resync))
            self._queue.clear()
            self._queue.append(RESYNC)
        self._queue.append(item)
        self._wake.set()

    async def next(self, timeout_s: float) -> Event | Resync | None:
        """The next event, or None when nothing came within `timeout_s`."""
        if not self._queue:
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout_s)
            except TimeoutError:
                return None
        self._sent += 1
        return self._queue.popleft()


class Fanout:
    """Every open screen in this process."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._open: set[Subscription] = set()

    def subscription(self, viewer: Watcher) -> Subscription:
        return Subscription(self, viewer, self._size)

    def add(self, subscription: Subscription) -> None:
        self._open.add(subscription)

    def remove(self, subscription: Subscription) -> None:
        self._open.discard(subscription)

    def deliver(self, event: Event) -> int:
        """Hand `event` to each open screen that may be shown it; how many it went to."""
        to = [s for s in self._open if shown_to(event, s.viewer)]
        for subscription in to:
            subscription.offer(event)
        return len(to)

    def resync(self) -> None:
        """Tell every open screen it may have missed something."""
        for subscription in self._open:
            subscription.offer(RESYNC)

    def __len__(self) -> int:
        return len(self._open)
