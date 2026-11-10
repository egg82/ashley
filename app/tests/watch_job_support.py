"""Fakes for the watch job tests: a `Watch` builder, an in-memory `Watches` that records what it was told, and kinds
that answer as scripted."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ashley.criteria.condition import Condition
from ashley.watches.config import CONFIG
from ashley.watches.diff import Items
from ashley.watches.kinds import Kind
from ashley.watches.model import Arm, Armed, Check, Counts, Read, State, Watch
from ashley.watches.watches import Watches, WatchesUnavailable

NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)
SESSION = CONFIG.kinds["claude_session"]


def watch(watch_id: int = 1, baseline: Items | None = None, *, kind: str = "claude_session", target: str = "s1",
          person: int = 7, household: int = 1, state: State = "armed", failures: int = 0, version: int = 0,
          series: int = 0, until: Condition | None = None, when: Condition = SESSION.when) -> Watch:
    return Watch(watch_id, household, person, kind, target, "label", None, "ashley", SESSION.track, when, until, None,
                 15, NOW + timedelta(hours=1), state, None, failures, version, series, baseline, NOW, NOW, None, None)


def session(status: str, seq: int, target: str = "s1") -> Items:
    return {target: {"status": status, "seq": seq}}


@dataclass
class FakeWatches(Watches):
    """`due_rows` come back from `due`; every `record` lands in `recorded`; `accept` false refuses them."""

    due_rows: tuple[Watch, ...] = ()
    recorded: list[tuple[int, int, Check]] = field(default_factory=list[tuple[int, int, Check]])
    expired: Counts = Counts(0, 0)
    accept: bool = True
    down: bool = False
    calls: list[str] = field(default_factory=list[str])

    async def arm(self, arm: Arm) -> Armed:
        raise AssertionError("not used")

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise AssertionError("not used")

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        raise AssertionError("not used")

    async def get(self, watch_id: int) -> Watch | None:
        raise AssertionError("not used")

    async def due(self, limit: int) -> tuple[Watch, ...]:
        self.calls.append("due")
        return self.due_rows[:limit]

    async def record(self, watch_id: int, version: int, check: Check) -> bool:
        self.recorded.append((watch_id, version, check))
        return self.accept

    async def expire(self, keep_s: float) -> Counts:
        self.calls.append("expire")
        if self.down:
            raise WatchesUnavailable("down")
        return self.expired


@dataclass
class ScriptedKind(Kind):
    """Answers `reads` for the watches of each group; `boom` raises; `hang` never answers."""

    name: str = "claude_session"
    reads: Mapping[int, Read] = field(default_factory=dict[int, Read])
    boom: bool = False
    hang: bool = False
    groups: list[tuple[int, ...]] = field(default_factory=list[tuple[int, ...]])

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        self.groups.append(tuple(w.id for w in group))
        if self.boom:
            raise RuntimeError("secret-looking message")
        if self.hang:
            import asyncio
            await asyncio.sleep(3600)
        return self.reads
