"""Helpers for the blind Watches job tests (`decisions.md`, "Watches wake her when what a read returns changes, until a
condition or a time"): the pure judge, the `claude_session` kind and the `watches` job, driven against a recording fake of
the `Watches` store and a scripted `Kind`, so no database is needed. One tick at a time.

The implementation did not exist when these were written. Every name, signature and shape guessed beyond the design is in
the ASSUMPTIONS block below and nowhere else; they are listed with the spec phrase each rests on in
`~/scratch/ashley/watches/watch-job-blind/assumptions.txt`."""

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from ashley import services

# --- ASSUMPTIONS: change here only -------------------------------------------------------------------------------

import ashley.watches.model as model
import ashley.watches.judge as judge_mod
import ashley.watches.kinds as kinds_mod
import ashley.watches.watches as store_mod
import ashley.watches.config as config_mod
import ashley.watches.job as job
import ashley.watches.claude_session as session_mod
import ashley.criteria.items as items_mod

# A1 the value types are in `ashley.watches.model`: Watch, Group, Counts, ReadFailed(reason), and the checks
#    Baseline(items), Quiet(ends), Woke(items, changes, ends), Failed(reason). Items is a plain nested mapping,
#    item identity -> {tracked field -> scalar}.
Watch, Counts, ReadFailed = model.Watch, model.Counts, model.ReadFailed
Baseline, Quiet, Woke, Failed = model.Baseline, model.Quiet, model.Woke, model.Failed
# A2 `judge(watch, read) -> Check`, pure and synchronous.
# A3 `Watch` takes keyword fields named as the migration's columns (see watch_of); `Group(kind, household_id, person_id,
#    watches)`; `Counts(expired, pruned)`.
# A4 a condition is a tuple of alternatives, each a tuple of `ItemPredicate(kind=, field=, value=, values=, of=, negate=)`
#    from `ashley.criteria.items`; `of` is "after" or "before".
ItemPredicate = items_mod.ItemPredicate
# A5 a change (`Woke.changes` entries) has `.id`, `.kind` ("new", "changed", "gone"), `.before` and `.after` (a field
#    mapping, or None on the missing side).
# A6 the store is `ashley.watches.watches.Watches` (a locator Service) with the methods of the method table, and
#    `WatchesUnavailable`; `Watches.null()` is the Null Object.
Watches, WatchesUnavailable = store_mod.Watches, store_mod.WatchesUnavailable
# A7 the kinds are `Kind` (`async read(group)`), a `Kinds` locator service with `of(name) -> Kind` that answers
#    `NullKind()` for a name it does not know, and the `claude_session` kind is `ClaudeSession()` taking its services
#    (Bridge, Connections) from the locator.
Kind, Kinds, NullKind = kinds_mod.Kind, kinds_mod.Registry, kinds_mod.NullKind
ClaudeSession = session_mod.ClaudeSession
# A8 the job module has `NAME == "watches"`, `async tick(config)` (raises WatchesUnavailable when the store is
#    unavailable) and `async run(config, sleep)` (tick, then `await sleep(config.tick_s)`, until cancelled; keeps going
#    past WatchesUnavailable). Config is `ashley.watches.config.WatchesConfig`, a dataclass with tick_s, batch,
#    read_timeout_s, fail_after, retry_s, keep_s (and the rest of watches.json), and `CONFIG` is the shipped one.
WatchesConfig, CONFIG = config_mod.WatchesConfig, config_mod.CONFIG
# A9 `CONFIG.kinds["claude_session"]` has `.when` and `.handoff_until` equal to the conditions in the spec.
# A10 failure slugs from the claude_session kind: `herdr_unavailable` -> "unreachable"; no herdr connection ->
#     "not_connected"; any other BridgeFailed -> some slug of the spec's closed list, never Items.
SLUGS = ("unreachable", "not_connected", "refused", "bad_result", "too_many_items", "unknown_kind")
# A11 the job's log events: `watches.tick` with expired, pruned, due, baselines, quiet, woke, failed, paused, resumed,
#     ended, duration_ms; `watches.read_failed` with kind, reason, watches (how many); `watches.unavailable` once per
#     run of failed ticks. paused = an armed watch whose Failed check reaches `fail_after` failures; resumed = a paused
#     watch whose check is not Failed; ended = a check with `ends` true.
# A12 the job tells the kind's group watches apart by `Watch.id`, and a Kind's result is keyed by that id.
# A13 a kind that raises, or does not answer within `read_timeout_s`, fails every watch in its group (the reason is not
#     fixed); a watch with no entry in a kind's answer is not relied on.
# A14 the Bridge fake is `ashley.herdr.bridge.Bridge`; Connections are the existing HeldConnections of money_support.

HOUSEHOLD, PERSON, OTHER_PERSON = 1, 7, 8
KIND = "claude_session"
BASE = "https://127.0.0.1:7843#sha256=" + "0" * 64
EPOCH = datetime(2026, 11, 1, tzinfo=timezone.utc)
FAR = EPOCH + timedelta(days=30)

Scalars = Mapping[str, Any]


def pred(kind: str, field_: str | None = None, of: str = "after", negate: bool = False, **extra: Any) -> Any:
    fields: dict[str, Any] = dict(kind=kind, field=field_, of=of, negate=negate, **extra)
    return ItemPredicate(**fields)


def judged(watch: Any, read: Any) -> Any:
    return judge_mod.judge(read, watch)


def watch_of(id_: int = 1, **over: Any) -> Any:
    fields: dict[str, Any] = dict(
        id=id_, household_id=HOUSEHOLD, person_id=PERSON, kind=KIND, target=f"s{id_}", label="label", bench_id=None,
        armed_by="handoff", track=("status", "seq"), when=DEFAULT_WHEN, until=DEFAULT_UNTIL, tools=None, interval_s=15,
        expires_at=FAR, state="armed", reason=None, failures=0, version=3, series=0, baseline=None, next_check_at=EPOCH,
        armed_at=EPOCH, last_woke_at=None, ended_at=None)
    fields.update(over)
    return Watch(**fields)


# --- the spec's conditions, written out ----------------------------------------------------------------------------

DEFAULT_WHEN = (
    (pred("one_of", "status", values=("blocked", "done")), pred("changed", "seq")),
    (pred("equals", "status", value="idle"), pred("changed", "seq"), pred("equals", "status", "before", True, value="done")))
DEFAULT_UNTIL = ((pred("gone"),),)
NEVER = ((pred("equals", "status", value="no-such-status"),),)


def one(sid: str, status: str, seq: int) -> dict[str, dict[str, Any]]:
    return {sid: {"status": status, "seq": seq}}


def state(*parts: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for part in parts:
        out.update(part)
    return out


def kinds_of(check: Any) -> list[tuple[str, str]]:
    return sorted((c.id, c.kind) for c in check.changes)


# --- the fake store and the scripted kind --------------------------------------------------------------------------

class FakeWatches(Watches):
    """The Watches store in memory: `queue` is what `due` offers (cut to the limit asked), every call is recorded, and
    `recorded` returns what `record` answers (True stores nothing and says so)."""

    def __init__(self, queue: list[Any] | None = None) -> None:
        self.queue: list[Any] = queue or []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.recorded: Callable[[int, int, Any], bool] = lambda i, v, c: True
        self.counts: Any = Counts(0, 0)
        self.broken: Exception | None = None

    def named(self, name: str) -> list[tuple[Any, ...]]:
        return [args for n, args in self.calls if n == name]

    def checks(self) -> dict[int, Any]:
        return {i: c for i, _, c in self.named("record")}

    async def expire(self, keep_s: float) -> Any:
        self.calls.append(("expire", (keep_s,)))
        if self.broken is not None:
            raise self.broken
        return self.counts

    async def due(self, limit: int) -> tuple[Any, ...]:
        self.calls.append(("due", (limit,)))
        if self.broken is not None:
            raise self.broken
        return tuple(self.queue[:limit])

    async def record(self, watch_id: int, version: int, check: Any) -> bool:
        self.calls.append(("record", (watch_id, version, check)))
        return self.recorded(watch_id, version, check)

    async def arm(self, arm: Any) -> Any:
        raise AssertionError("the job never arms")

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise AssertionError("the job never disarms")

    async def live(self, household_id: int, person_id: int) -> tuple[Any, ...]:
        raise AssertionError("the job never lists")

    async def get(self, watch_id: int) -> Any:
        raise AssertionError("the job never reads one")


@dataclass(frozen=True)
class Group:
    """What a kind is asked to read, seen by the tests: the watches of one kind, household and person."""

    kind: str
    household_id: int
    person_id: int
    watches: tuple[Any, ...]

    @classmethod
    def of(cls, watches: Any) -> "Group":
        first = watches[0]
        return cls(first.kind, first.household_id, first.person_id, tuple(watches))


class Hang(Exception):
    """A scripted answer that never comes."""


class FakeKind(Kind):
    """Answers each group from `world` (watch id -> Items | ReadFailed) unless `script` says otherwise: an Exception is
    raised, `Hang()` waits for ever."""

    def __init__(self, world: Mapping[int, Any] | None = None) -> None:
        self.world: dict[int, Any] = dict(world or {})
        self.groups: list[Any] = []
        self.script: Callable[[Any], Any] | None = None

    async def read(self, group: Any) -> Mapping[int, Any]:
        group = Group.of(group)
        self.groups.append(group)
        got = self.script(group) if self.script else None
        if isinstance(got, Hang):
            await asyncio.Event().wait()
        if isinstance(got, Exception):
            raise got
        return got if got is not None else {w.id: self.world[w.id] for w in group.watches}


def fake_kinds(**by_name: Any) -> Any:
    class Named(Kind):
        def __init__(self, name: str, inner: Any) -> None:
            self.name, self.inner = name, inner

        async def read(self, group: Any) -> Any:
            return await self.inner.read(group)

    return Kinds([Named(name, kind) for name, kind in by_name.items()])


@dataclass
class Harness:
    store: Any
    kind: Any
    config: Any
    kinds: Any

    async def tick(self) -> None:
        await job.tick(self.config, self.kinds)

    def read_ids(self) -> list[list[int]]:
        return [sorted(w.id for w in g.watches) for g in self.kind.groups]


CONF = replace(CONFIG, tick_s=0.01, batch=10, read_timeout_s=0.2, fail_after=3, retry_s=60.0, keep_s=1000.0)


def harness(watches: list[Any], world: Mapping[int, Any], config: Any = CONF) -> Harness:
    store, kind = FakeWatches(list(watches)), FakeKind(world)
    services.register(Watches, store)
    return Harness(store, kind, config, fake_kinds(**{KIND: kind, "fake": kind}))


def for_person(person: int, answer: Any) -> Callable[[Any], Any]:
    """A kind script that answers `answer` to that person's group and the world to every other."""
    def script(group: Any) -> Any:
        return answer if group.person_id == person else None
    return script


def always(answer: Any) -> Callable[[Any], Any]:
    def script(group: Any) -> Any:
        return answer
    return script


def refusing(*watch_ids: int) -> Callable[[int, int, Any], bool]:
    """A `record` answer that refuses those watches."""
    def answer(watch_id: int, version: int, check: Any) -> bool:
        return watch_id not in watch_ids
    return answer


def run(scenario: Coroutine[Any, Any, None], limit: float = 15.0) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, limit)

    asyncio.run(bounded())
