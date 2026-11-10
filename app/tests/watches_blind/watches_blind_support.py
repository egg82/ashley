"""Helpers for the blind Watches contract tests (`decisions.md`, "Watches wake her when what a read returns changes,
until a condition or a time"): a migrated database per test, raw SQL to set up households and people, to read, insert
and age watches and wakes, and the store built from a `Database`.

ASSUMPTIONS (every guess beyond the design lives in this block and the helpers under it; the list with the spec phrase
each rests on is `~/scratch/ashley/watches/watch-store-blind/assumptions.txt`):
  A1  Value types live in `ashley.watches.model`: Arm, Armed, Watch, Baseline, Quiet, Woke, Failed, Counts.
  A2  Arm is built by keyword with the method table's field names plus household_id, person_id; `when`/`until` are
      conditions (see A4); `track` and `tools` are tuples; `baseline` is items or None.
  A3  Items are `{identity: {field: scalar}}`. Armed has `.id`, `.new`. Watch has the column names as attributes.
  A4  A condition is a tuple of alternatives, each a tuple of `ashley.criteria.items.ItemPredicate(kind=, field=, ...)`.
  A5  Baseline(items), Quiet(ends), Woke(items, changes, ends), Failed(reason); `changes` is a tuple of
      `ashley.criteria.record.Change(id=, kind=, before=, after=)`; `ends` is a bool.
  A6  Settings reach the store by its constructor as a `WatchesConfig`: PostgresWatches(database, config).
  A7  Counts has `.expired` and `.pruned`.
  A8  The wake's `changes` JSON: what, series, since, ended, items[{id, kind, before, after}] (the keys of
      `Change`); a paused wake's has `reason`.
  A9  An armed watch is due at once unless a test sets next_check_at, so tests always set it.
  A11 `bench_id` has no foreign key a bare integer would break.
  A10 The wake's `event` column is not asserted; a watch wake has no `made_by` requirement."""

import json
from collections.abc import AsyncGenerator, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from ashley.criteria.items import ItemPredicate, Kind
from ashley.criteria.record import Change, ChangeKind
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.watches.config import CONFIG
from ashley.watches.model import Arm, ArmedBy, Baseline, FailReason, Failed, Quiet, Woke
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from contract.conversations_support import household, person, scalar
from contract.conversations_support import run as run_bounded
from psycopg.types.json import Jsonb

KIND = "claude_session"
INTERVAL_S = 30
FAIL_AFTER = 3
RETRY_S = 600
MAX_LIVE = 5
MAX_ALTS = 2
MAX_PREDS = 2
KEEP_S = 3600
TRACK = ("status", "seq")
Items = Mapping[str, Mapping[str, Any]]


def run(scenario: Coroutine[Any, Any, None], limit: float = 25.0) -> None:
    run_bounded(scenario, limit)


def make(database: Database) -> Watches:
    return PostgresWatches(database, replace(CONFIG, fail_after=FAIL_AFTER, retry_s=RETRY_S, max_live=MAX_LIVE,
                                             max_alternatives=MAX_ALTS, max_predicates=MAX_PREDS, keep_s=KEEP_S))


# --- guessed shapes: change here only ------------------------------------------------------------------------------


def pred(kind: Kind, field: str | None = None, **more: Any) -> ItemPredicate:
    """One predicate: `pred("equals", "status", value="done")`, `pred("gone")`, `pred("changed", "seq")`."""
    return ItemPredicate(kind=kind, field=field, **more)


def cond(*alternatives: tuple[ItemPredicate, ...]) -> tuple[tuple[ItemPredicate, ...], ...]:
    return tuple(alternatives)


WHEN = cond((pred("changed", "seq"),))
UNTIL_GONE = cond((pred("gone"),))


def change(identity: str, kind: ChangeKind, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> Change:
    return Change(id=identity, kind=kind, before=before, after=after)


def baseline(items: Items) -> Baseline:
    return Baseline(items)


def quiet(ends: bool = False) -> Quiet:
    return Quiet(ends)


def woke(items: Items, changes: tuple[Change, ...] = (), ends: bool = False) -> Woke:
    return Woke(items, changes or (change("s1", "changed", {"seq": 1}, {"seq": 2}),), ends)


def failed(reason: FailReason = "unreachable") -> Failed:
    return Failed(reason)


def item_id(entry: Mapping[str, Any]) -> str:
    return str(entry["id"])


def item_kind(entry: Mapping[str, Any]) -> str:
    return str(entry["kind"])


def armed_id(armed: Any) -> int:
    return int(armed.id)


def armed_new(armed: Any) -> bool:
    return bool(armed.new)


def wid(watch: Any) -> int:
    return int(watch.id)


def wfield(watch: Any, name: str) -> Any:
    """A `Watch` attribute by its column name (`state`, `reason`, `version`, `series`, `target`, ...)."""
    return getattr(watch, name)


def expired_of(counts: Any) -> int:
    return int(counts.expired)


def pruned_of(counts: Any) -> int:
    return int(counts.pruned)


def in_hours(hours: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def make_arm(w: "World", target: str = "s1", *, who: int | None = None, kind: str = KIND, armed_by: ArmedBy = "ashley",
             when: Any = WHEN, until: Any = None, tools: tuple[str, ...] | None = None, interval_s: int = INTERVAL_S,
             expires_at: datetime | None = None, items: Items | None = None, track: tuple[str, ...] = TRACK,
             bench_id: int | None = None, label: str = "the session") -> Arm:
    return Arm(household_id=w.hid, person_id=who or w.owner, kind=kind, target=target, label=label, bench_id=bench_id,
               armed_by=armed_by, track=track, when=when, until=until, tools=tools, interval_s=interval_s,
               expires_at=expires_at or in_hours(24), baseline=items)


# --- the world -----------------------------------------------------------------------------------------------------


@dataclass
class World:
    url: str
    store: Watches
    hid: int
    owner: int
    mate: int
    other_hid: int
    stranger: int

    async def arm(self, target: str = "s1", **more: Any) -> int:
        return armed_id(await self.store.arm(make_arm(self, target, **more)))

    async def armed_due(self, target: str = "s1", **more: Any) -> tuple[int, int]:
        """A watch armed and made due now: its id and version."""
        wid_ = await self.arm(target, **more)
        make_due(self.url, wid_)
        return wid_, version_of(self.url, wid_)

    async def woken(self, target: str = "s1") -> int:
        """A watch with one unsettled `changed` wake."""
        wid_, version = await self.armed_due(target)
        assert await self.store.record(wid_, version, woke({"s1": {"seq": 2}}))
        return wid_


def make_world(url: str, database: Database) -> World:
    hid = household(url, "home")
    other_hid = household(url, "elsewhere")
    return World(url, make(database), hid, person(url, hid, "owner"), person(url, hid, "mate"), other_hid,
                 person(url, other_hid, "stranger"))


@asynccontextmanager
async def opened(url: str) -> AsyncGenerator[World]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield make_world(url, database)
    finally:
        await database.close()


def scenario(url: str, body: Any) -> None:
    async def go() -> None:
        async with opened(url) as w:
            await body(w)

    run(go())


# --- raw rows ------------------------------------------------------------------------------------------------------


def _rows(url: str, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute(query.encode(), params)
        names = [c.name for c in cur.description or ()]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def row(url: str, watch: int) -> dict[str, Any]:
    found = _rows(url, "SELECT * FROM watches WHERE id = %s", (watch,))
    assert found, f"no watch {watch}"
    return found[0]


def exists(url: str, watch: int) -> bool:
    return bool(_rows(url, "SELECT 1 FROM watches WHERE id = %s", (watch,)))


def count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM watches"))


def snapshot(url: str) -> str:
    """Every watch and wake row as text, so a call that must write nothing can be compared."""
    return str(scalar(url, "SELECT coalesce((SELECT string_agg(t::text, '|' ORDER BY id) FROM watches t), '') || '#' || "
                           "coalesce((SELECT string_agg(t::text, '|' ORDER BY id) FROM wakes t), '')"))


def wakes_of(url: str, watch: int) -> list[dict[str, Any]]:
    return _rows(url, "SELECT * FROM wakes WHERE watch_id = %s ORDER BY id", (watch,))


def version_of(url: str, watch: int) -> int:
    return int(row(url, watch)["version"])


def changes_of(wake: Mapping[str, Any]) -> dict[str, Any]:
    raw = wake["changes"]
    out: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
    return out


def seconds_until(url: str, watch: int, column: str) -> float:
    assert column in ("next_check_at", "expires_at")
    return float(scalar(url, f"SELECT extract(epoch FROM {column} - clock_timestamp()) FROM watches WHERE id = %s",
                        (watch,)))


def _exec(url: str, query: str, params: tuple[Any, ...]) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(query.encode(), params)


def make_due(url: str, watch: int, ago_s: float = 5) -> None:
    _exec(url, "UPDATE watches SET next_check_at = clock_timestamp() - make_interval(secs => %s) WHERE id = %s",
          (ago_s, watch))


def defer(url: str, watch: int, ahead_s: float = 600) -> None:
    _exec(url, "UPDATE watches SET next_check_at = clock_timestamp() + make_interval(secs => %s) WHERE id = %s",
          (ahead_s, watch))


def lapse(url: str, watch: int) -> None:
    """Move arming and expiry a day and a minute into the past, so the watch is past `expires_at`."""
    _exec(url, "UPDATE watches SET armed_at = armed_at - interval '2 days', "
               "expires_at = clock_timestamp() - interval '1 minute' WHERE id = %s", (watch,))


def age_ended(url: str, watch: int, seconds: float) -> None:
    """Move the whole of a watch's history `seconds` into the past."""
    _exec(url, "UPDATE watches SET armed_at = armed_at - make_interval(secs => %s), "
               "ended_at = ended_at - make_interval(secs => %s), expires_at = expires_at - make_interval(secs => %s) "
               "WHERE id = %s", (seconds, seconds, seconds, watch))


def settle_wakes(url: str, watch: int) -> None:
    _exec(url, "UPDATE wakes SET settled_at = now(), outcome = 'turn' WHERE watch_id = %s", (watch,))


def forbid_watch_wakes(url: str) -> None:
    """From now on every insert of a watch wake fails, as if its write broke after the watch row was changed."""
    _exec(url, "CREATE FUNCTION refuse_watch_wake() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
               "IF NEW.kind = 'watch' THEN RAISE EXCEPTION 'refused'; END IF; RETURN NEW; END $$", ())
    _exec(url, "CREATE TRIGGER refuse_watch_wake BEFORE INSERT ON wakes FOR EACH ROW EXECUTE FUNCTION refuse_watch_wake()",
          ())


def insert_watch(url: str, *, household_id: int, person_id: int, kind: str = KIND, target: str = "s1",
                 label: str = "the session", armed_by: str = "ashley", track: tuple[str, ...] = TRACK,
                 interval_s: int = INTERVAL_S, state: str = "armed", reason: str | None = None, failures: int = 0,
                 version: int = 0, series: int = 0, ended: bool = False) -> int:
    """A watches row written directly, so the database's own constraints are what answer."""
    return int(scalar(
        url, "INSERT INTO watches (household_id, person_id, kind, target, label, armed_by, track, when_clauses, "
             "interval_s, expires_at, state, reason, failures, version, series, next_check_at, ended_at) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now() + interval '1 day', %s, %s, %s, %s, %s, now(), "
             "CASE WHEN %s THEN now() END) RETURNING id",
        (household_id, person_id, kind, target, label, armed_by, list(track), Jsonb([[{"kind": "new"}]]), interval_s,
         state, reason, failures, version, series, ended)))


def insert_wake(url: str, *, household_id: int, person_id: int | None, kind: str = "watch", watch_id: int | None = None,
                changes: dict[str, Any] | None = None, device_id: int | None = None, event_id: str = "e1") -> int:
    return int(scalar(
        url, "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, watch_id, changes, "
             "device_id, made_by, brief) VALUES (%s, %s, %s, 'watch', now(), now(), %s, %s, %s, %s, "
             "CASE WHEN %s = 'reminder' THEN %s::bigint END, CASE WHEN %s = 'reminder' THEN 'x' END) RETURNING id",
        (household_id, kind, event_id, person_id, watch_id, None if changes is None else Jsonb(changes), device_id,
         kind, person_id, kind)))
