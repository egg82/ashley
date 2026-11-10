"""Helpers for the blind tests of a reply said outside the response to a message: an in-memory `Outbox`, a recording
`Clips`, a `sleep` that ends a `drain` after a set number of polls, and a wait on the running loop."""

import asyncio
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field

import pytest
from ashley import logs, services
from ashley.channels.model import Outbound
from ashley.channels.outbox import Later, Outbox, OutboxUnavailable
from ashley.channels.voice.clips import Clips, ClipsUnavailable, NewClip
from contract.conversations_support import events


class FakeOutbox(Outbox):
    """`add` records and answers ids from 1; `take` answers the waiting replies whose thread starts with the prefix,
    after raising each of `take_errors` once, in order."""

    def __init__(self) -> None:
        self.added: list[tuple[int, str, Outbound]] = []
        self.waiting: list[Later] = []
        self.add_error: Exception | None = None
        self.take_errors: list[Exception | None] = []
        self.prefixes: list[str] = []

    async def add(self, household_id: int, thread: str, outbound: Outbound) -> int:
        if self.add_error is not None:
            raise self.add_error
        self.added.append((household_id, thread, outbound))
        return len(self.added)

    async def take(self, prefix: str) -> list[Later]:
        self.prefixes.append(prefix)
        if self.take_errors:
            error = self.take_errors.pop(0)
            if error is not None:
                raise error
        mine = [w for w in self.waiting if w.thread.startswith(prefix)]
        self.waiting = [w for w in self.waiting if w not in mine]
        return mine


def unavailable() -> OutboxUnavailable:
    return OutboxUnavailable("down")


def waiting(thread: str, body: str, conversation_id: int = 41, medium: str = "spoken", age_ms: int = 2500,
            id_: int = 1) -> Later:
    assert medium in ("spoken", "text")
    return Later(id_, 1, thread, Outbound(conversation_id, "spoken" if medium == "spoken" else "text", body), age_ms)


class FakeClips(Clips):
    """Records each `add` as (device_id, body, since_wake_ms) and answers token `tok-<n>`; `error` fails them all."""

    def __init__(self) -> None:
        self.added: list[tuple[int, str, int]] = []
        self.error: ClipsUnavailable | None = None

    async def add(self, device_id: int, body: str, since_wake_ms: int) -> NewClip:
        if self.error is not None:
            raise self.error
        self.added.append((device_id, body, since_wake_ms))
        return NewClip(len(self.added), f"tok-{len(self.added)}")

    async def get(self, token: str) -> None:
        raise AssertionError("a reply said later stores a clip, it never fetches one")


@dataclass
class Polls:
    """A `sleep` for `drain` that records each wait and cancels the drain on the `stop_at`-th call."""

    stop_at: int
    waits: list[float] = field(default_factory=list[float])

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        if len(self.waits) >= self.stop_at:
            raise asyncio.CancelledError


async def drained(drain: Awaitable[None]) -> None:
    """Run a `drain` until its `Polls` stops it."""
    with pytest.raises(asyncio.CancelledError):
        await drain


async def until(condition: Callable[[], object], timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "the awaited condition never held"
        await asyncio.sleep(0.005)


@pytest.fixture
def outbox() -> Generator[FakeOutbox]:
    made = FakeOutbox()
    services.register(Outbox, made)
    yield made
    services.unregister(Outbox)


@pytest.fixture
def clips() -> Generator[FakeClips]:
    made = FakeClips()
    services.register(Clips, made)
    yield made
    services.unregister(Clips)


class Logged:
    """Everything printed to stdout since `logs.setup()`, collected across reads."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self.text = ""
        logs.setup()
        self.read()

    def read(self) -> str:
        self.text += self._capsys.readouterr().out
        return self.text

    def events(self, event: str) -> list[dict[str, str]]:
        return events(self.read(), event)
