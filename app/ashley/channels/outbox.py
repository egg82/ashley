"""Replies said to a thread outside the response to a message: the answer after "let me check" today, and later what
she says on her own (`decisions.md`, "A channel that pushes is an outbox"). Any pod adds one; the singleton holding the
thread's channel takes it and delivers it. Tunables are data, `outbox.json` beside this module: a reply waiting longer
than `stale_s` is dropped rather than delivered, and a channel looks for replies every `poll_s`."""

import json
from abc import abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import services
from ..conversations.inflight import Claim, InFlight
from ..conversations.model import NewTurn, Turn
from ..services import Service
from .model import Outbound

FILE = Path(__file__).with_name("outbox.json")


class OutboxError(Exception):
    """Base of what an Outbox raises on purpose."""


class OutboxUnavailable(OutboxError):
    """The outbox could not be reached. Transient."""


@dataclass(frozen=True)
class Later:
    """A reply waiting for its channel: said to `thread` of `household_id`, `age_ms` after it was added."""

    id: int
    household_id: int
    thread: str
    outbound: Outbound
    age_ms: int


@dataclass(frozen=True)
class Pushed:
    """A reply to queue for `thread` of `household_id`. `answers` is the person turn the reply answers, set on a held
    answer: should it wait past `stale_s` it is kept for the asker's next reply, not lost."""

    household_id: int
    thread: str
    outbound: Outbound
    answers: int | None = None


@dataclass(frozen=True)
class Config:
    stale_s: float
    poll_s: float

    def __post_init__(self) -> None:
        if min(self.stale_s, self.poll_s) <= 0:
            raise ValueError("outbox timings must be positive")


def load() -> Config:
    """The tunables shipped in `outbox.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != {"stale_s", "poll_s"}:
        raise ValueError("outbox.json has exactly stale_s and poll_s")
    return Config(float(raw["stale_s"]), float(raw["poll_s"]))


class Outbox(Service):
    @classmethod
    def null(cls) -> "Outbox":
        return NullOutbox()

    @abstractmethod
    async def add(self, household_id: int, thread: str, outbound: Outbound) -> int:
        """Queue `outbound` for `thread` of `household_id`; its id. Raises OutboxUnavailable."""

    @abstractmethod
    async def take(self, prefix: str) -> list[Later]:
        """Remove and return every reply waiting for a thread starting with `prefix`, oldest first, so each is taken
        once however many pods ask; replies older than `stale_s` are removed and not returned. Raises
        OutboxUnavailable."""

    async def answer(self, claim: Claim, turn: NewTurn, pushed: Sequence[Pushed],
                     after: Callable[[Turn], str] | None = None) -> Turn:
        """Her answer `turn` stored, ending the work `claim` holds (`InFlight.finish`, `after` as there), and each of
        `pushed` queued: all in one transaction or none, so a turn resumed after a kill is never queued twice and
        never stored unqueued. Raises what `InFlight.finish` raises, and OutboxUnavailable. This default queues and
        then stores, one after the other, which only an in-memory store may: an implementation over the database
        overrides it."""
        for p in pushed:
            await self.add(p.household_id, p.thread, p.outbound)
        return await services.get(InFlight).finish(claim, turn, after)


class NullOutbox(Outbox):
    """What an unwired process sees: nothing can be queued or taken."""

    async def add(self, household_id: int, thread: str, outbound: Outbound) -> int:
        raise OutboxUnavailable("no outbox is wired")

    async def take(self, prefix: str) -> list[Later]:
        raise OutboxUnavailable("no outbox is wired")

    async def answer(self, claim: Claim, turn: NewTurn, pushed: Sequence[Pushed],
                     after: Callable[[Turn], str] | None = None) -> Turn:
        raise OutboxUnavailable("no outbox is wired")
