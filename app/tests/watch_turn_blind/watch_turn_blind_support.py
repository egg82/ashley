"""Helpers for the blind tests of the Watches switch-over (`decisions.md`, "Watches wake her when what a read returns
changes, until a condition or a time"): the wake, the woken turn, arming on hand-off, the migration's data move and the
deletions. Built from the design alone.

Every guess beyond the design is in ASSUMPTIONS below and nowhere else: module paths of the store's types, the field
names of `Arm`, `Change` and `ItemPredicate`, the `WatchWake` shape, the wake's turn source. They are listed with the
spec phrase each rests on in ~/scratch/ashley/watches/watch-turn-blind/assumptions.txt."""

# ASSUMPTIONS --------------------------------------------------------------------------------------------------------
# A1 store types live in ashley.watches.watches: Watches, WatchesUnavailable, Arm, Armed, Watch, Baseline, Quiet, Woke, Failed
# A2 PostgresWatches(database) in ashley.watches.postgres
# A3 Arm is a dataclass taking keyword fields named as the spec's method table lists them (plus household_id, person_id)
# A4 Items is a plain mapping {identity: {field: scalar}}; for claude_session the identity is the session id
# A5 ItemPredicate(kind=..., field=...) and Change(identity, how, before, after) construct positionally/by keyword
# A6 Woke(items, changes, ends): `changes` is a tuple of Change; a new watch is at version 0 and a baseline-carrying arm keeps it
# A7 a watch wake's turn source is f"wake:{wake_id}" (as every other wake's)
# A8 the household's turn text carries the label and the status; a woken turn's reading-only tools are the ones with reads=True
# A9 the migration is the revision whose file drops herdr_watched; defaults: interval_s 15, handoff_hours 72, track (status, seq)
# --------------------------------------------------------------------------------------------------------------------

import importlib
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from alembic.script import Script, ScriptDirectory
from ashley import services
from ashley.criteria.items import ItemPredicate
from ashley.criteria.record import Change, ChangeKind, Fields
from ashley.db.migrate import alembic_config
from ashley.db.pool import PoolDatabase
from ashley.inference.model import Prompt, ToolSpec
from ashley.watches.postgres import PostgresWatches
from ashley.watches.diff import Items
from ashley.watches.model import Arm, ArmedBy, FailReason, Failed, Woke
from ashley.watches.watches import Watches
from contract.conversations_support import scalar
from contract.test_inflight_resume import World
from wb_runner_support import Stack, stack
from ashley.tools.tools import Catalogue, Tools
from ashley.inference.model import ToolCall, ToolResult

KIND = "claude_session"
SESSION = "sess-wtb-1"
LABEL = "PLANTED-LABEL-wtb"
HOURS = 3600.0
LONG_S = 10 * 86400


def now() -> datetime:
    return datetime.now(UTC)


def run_sql(url: str, query: str, params: tuple[object, ...] = ()) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(query.encode(), params)


def rows(url: str, query: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(query.encode(), params).fetchall()


# --- guessed shapes: change here only ---------------------------------------------------------------------------

DEFAULT_WHEN = ((ItemPredicate(kind="changed", field="seq"),),)
GONE = ((ItemPredicate(kind="gone"),),)


def items_of(status: str, seq: int, session: str = SESSION) -> Items:
    return {session: {"status": status, "seq": seq}}


def change(how: ChangeKind, before: Fields | None, after: Fields | None, session: str = SESSION) -> Change:
    return Change(session, how, before, after)


def make_arm(world: World, *, target: str = SESSION, armed_by: ArmedBy = "ashley", bench_id: int | None = None,
             tools: tuple[str, ...] | None = None, hours: float = 24.0, label: str = LABEL,
             baseline: Items | None = None, until: Any = None) -> Arm:
    return Arm(household_id=world.who.household_id, person_id=world.who.id, kind=KIND, target=target, label=label,
               bench_id=bench_id, armed_by=armed_by, track=("status", "seq"), when=DEFAULT_WHEN, until=until,
               tools=tools, interval_s=15, expires_at=now() + timedelta(hours=hours),
               baseline=items_of("working", 1, target) if baseline is None else baseline)


def arm_fields(arm: Any) -> dict[str, object]:
    """What `Watches.arm` was given, by the names the method table uses."""
    return {n: getattr(arm, n) for n in ("kind", "target", "label", "bench_id", "armed_by", "track", "until", "tools",
                                         "baseline", "expires_at", "household_id", "person_id")}


def is_gone_only(until: Any) -> bool:
    """Whether `until` is the clause `[[gone]]`."""
    return until is not None and len(until) == 1 and len(until[0]) == 1 and until[0][0].kind == "gone"


# --- the rig: Wakes, Watches, Workshop, the turn loop and a scripted model on one database ------------------------------


@dataclass
class ReadsAndChanges(Tools):
    """One tool that reads and two that change; `ran` is every call that reached one."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        specs = (ToolSpec("lamp_state", "read the lamp", {"type": "object"}, reads=True, outside=False),
                 ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False, outside=False),
                 ToolSpec("garage_open", "open the garage", {"type": "object"}, reads=False, outside=False))
        return Catalogue(specs, "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, '{"ok": true}')


def tool_names(prompt: Prompt) -> set[str]:
    return {t.name for t in prompt.tools}


def messages_text(prompt: Prompt) -> str:
    return repr(prompt.messages)


@dataclass
class Rig:
    s: Stack
    watches: Watches
    world: World

    @property
    def url(self) -> str:
        return self.world.url

    async def armed(self, **over: Any) -> int:
        got = await self.watches.arm(make_arm(self.world, **over))
        return int(got.id)

    async def version_of(self, watch_id: int) -> int:
        got = await self.watches.get(watch_id)
        assert got is not None
        return int(got.version)

    async def woke(self, watch_id: int, status: str = "done", seq: int = 2, ends: str | None = None,
                   before: str = "working", before_seq: int = 1) -> int:
        """Record a check that woke her for `watch_id`, as the job would; the stored wake's id."""
        changes = (change("changed", {"status": before, "seq": before_seq}, {"status": status, "seq": seq}),)
        recorded = await self.watches.record(watch_id, await self.version_of(watch_id),
                                             Woke(items_of(status, seq), changes, ends is not None))
        assert recorded is True
        return self.wake_of(watch_id)

    async def paused(self, watch_id: int, reason: FailReason = "unreachable") -> int:
        """Fail reads until the watch pauses; the `paused` wake's id."""
        for _ in range(50):
            await self.watches.record(watch_id, await self.version_of(watch_id), Failed(reason))
            got = await self.watches.get(watch_id)
            if got is not None and str(got.state) == "paused":
                return self.wake_of(watch_id)
        raise AssertionError("the watch never paused")

    def wake_of(self, watch_id: int) -> int:
        found = rows(self.url, "SELECT id FROM wakes WHERE watch_id = %s ORDER BY id DESC LIMIT 1", (watch_id,))
        assert found, "no wake was stored"
        return int(found[0][0])

    def outcome(self, wake_id: int) -> object:
        return scalar(self.url, "SELECT outcome FROM wakes WHERE id = %s", (wake_id,))

    def turns_on(self, thread: str) -> list[tuple[str, str, str | None]]:
        got = rows(self.url, "SELECT t.author, t.text, t.source FROM turns t JOIN conversations c "
                             "ON c.id = t.conversation_id WHERE c.thread = %s ORDER BY t.id", (thread,))
        return [(a, t, s) for a, t, s in got]

    def household_turns(self) -> list[tuple[str, str | None]]:
        got = rows(self.url, "SELECT text, source FROM turns WHERE author = 'household' ORDER BY id")
        return [(t, s) for t, s in got]

    async def bench(self) -> int:
        return int((await self.s.workshop.open(self.s.owner, "talk")).id)

    async def close_bench(self, bench_id: int) -> None:
        await self.s.workshop.close(self.s.owner, bench_id)

    def age(self, wake_id: int, seconds: float) -> None:
        run_sql(self.url, "UPDATE wakes SET received_at = received_at - make_interval(secs => %s), "
                          "due_at = due_at - make_interval(secs => %s) WHERE id = %s", (seconds, seconds, wake_id))


@asynccontextmanager
async def rig(world: World, tools: Tools | None = None) -> AsyncGenerator[Rig]:
    async with stack(world) as s:
        db = PoolDatabase(world.url, connect_timeout_s=5.0)
        await db.open()
        watches = PostgresWatches(db)
        services.register(Watches, watches)
        if tools is not None:
            for pod in (world.first, world.second):
                holder: Any = pod
                holder.tools = tools
            world.as_pod(world.first)
        try:
            yield Rig(s, watches, world)
        finally:
            services.unregister(Watches)
            await db.close()


# --- the migration ----------------------------------------------------------------------------------------------------


def revision_dropping(table: str) -> tuple[str, str]:
    """(this revision, the one before it) for the one revision whose upgrade drops `table`, found by content so a
    renumber changes nothing."""
    script = ScriptDirectory.from_config(alembic_config(""))
    drops = re.compile(rf"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?{table}\b", re.I)
    found: list[Script] = []
    for r in script.walk_revisions():
        with open(r.path) as f:
            upgrade = f.read().split("def downgrade")[0].split("def upgrade")[-1]
        if drops.search(upgrade):
            found.append(r)
    assert len(found) == 1, [r.revision for r in found]
    assert isinstance(found[0].down_revision, str)
    return found[0].revision, found[0].down_revision


def importable(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError:
        return False
    return True
