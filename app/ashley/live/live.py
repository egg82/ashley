"""The Live service (`ashley.services`): what the open screens should know changed, right now (`decisions.md`, "Open
screens learn what changed through Live"). Publishers call `publish` and never wait on it; each screen holds a
`Subscription`. Tunables are data, `live.json` beside this module: `queue_size`, the events one screen may fall behind
by before it is told to resync; `heartbeat_s`, the longest a stream goes without a byte; `stream_s`, how long one
stream stays open before the screen reconnects (and its session is checked again); `thinking_at_most_s`, how long a
screen shows her thinking without hearing the turn end; `reconnect_max_s`, the longest wait between attempts to
reach the database's notifications; `pending_size`, the events one process may hold unsent before it drops new ones;
`present_s`, how long after its last heartbeat a person's open screen still counts as open (`ashley.live.screens`)."""

import json
from abc import abstractmethod
from dataclasses import dataclass, fields
from pathlib import Path

from ..services import Service
from .events import Event, Watcher
from .fanout import Subscription

FILE = Path(__file__).with_name("live.json")


class LiveUnavailable(Exception):
    """No feed is wired, so a screen must look for itself."""


@dataclass(frozen=True)
class Config:
    queue_size: int
    heartbeat_s: float
    stream_s: float
    thinking_at_most_s: float
    reconnect_max_s: float
    pending_size: int
    present_s: float

    def __post_init__(self) -> None:
        timings = (self.heartbeat_s, self.stream_s, self.thinking_at_most_s, self.reconnect_max_s, self.present_s)
        if self.queue_size < 2 or self.pending_size < 1 or min(timings) <= 0:
            raise ValueError("live timings and pending_size must be positive, queue_size at least 2")


def load() -> Config:
    """The tunables shipped in `live.json`. Raises ValueError when one is missing, unknown or out of range."""
    raw = json.loads(FILE.read_text())
    names = {f.name for f in fields(Config)}
    if set(raw) != names:
        raise ValueError(f"live.json has exactly {sorted(names)}")
    return Config(int(raw["queue_size"]), float(raw["heartbeat_s"]), float(raw["stream_s"]),
                  float(raw["thinking_at_most_s"]), float(raw["reconnect_max_s"]), int(raw["pending_size"]), float(raw["present_s"]))


class Live(Service):
    @classmethod
    def null(cls) -> "Live":
        return NullLive()

    @abstractmethod
    def publish(self, event: Event) -> None:
        """Hand `event` to every open screen, on any pod of either site, that may be shown it. Never waits and never
        raises: a lost event costs a screen a refetch, never a turn."""

    @abstractmethod
    def subscribe(self, viewer: Watcher) -> Subscription:
        """A subscription for one screen of `viewer`'s, fed between entering and leaving it with what `viewer` may be
        shown (`events.shown_to`), and a resync whenever something may have been missed. Raises LiveUnavailable."""


class NullLive(Live):
    """What an unwired process sees: nothing is published, and no screen can subscribe, so it falls back to looking
    for itself instead of waiting on a feed that never speaks."""

    def publish(self, event: Event) -> None:
        pass

    def subscribe(self, viewer: Watcher) -> Subscription:
        raise LiveUnavailable("no live feed is wired")
