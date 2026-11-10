"""Helpers for the blind Errands contract tests (`decisions.md`, "What she could not do for want of a source"): a
migrated database per test, raw SQL to set up a household, people, a conversation and person turns and to age an
errand, and the store built the way sibling Postgres services are, from a `Database`.

Every guess beyond the design is here and only here: where the value types live, their field names, the argument
shapes of `claim` and `untold`. They are listed in `~/scratch/ashley/errands/blind-ambiguities.txt`."""

from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.errands.errands import Errands
from ashley.errands.postgres import PostgresErrands
from contract.conversations_support import household, person, scalar
from contract.conversations_support import run as run_bounded

HOUSE = "house"
SEARCH = "search"
LONG_S = 1_000_000


def run(scenario: Coroutine[Any, Any, None], limit: float = 25.0) -> None:
    run_bounded(scenario, limit)


def make(database: Database) -> Errands:
    return PostgresErrands(database)


# --- guessed shapes: change here only ---------------------------------------------------------------------------


def errand_id(errand: Any) -> int:
    """A claimed errand's id."""
    return int(errand.id)


def done_id(done: Any) -> int:
    return int(done.id)


def done_result(done: Any) -> str:
    return str(done.result)


def interrupted_of(counts: Any) -> int:
    return int(counts.interrupted)


def expired_of(counts: Any) -> int:
    return int(counts.expired)


def state_name(state: Any) -> str:
    return str(state)


async def claim(errands: Errands, answering: tuple[str, ...], max_age_s: int = LONG_S) -> int | None:
    """The id of the errand `claim` took, None when it took none."""
    got = await errands.claim(frozenset(answering), max_age_s)
    return None if got is None else errand_id(got)


async def untold(errands: Errands, hearer: int, limit: int = 50) -> list[int]:
    """The ids `untold` answered for this hearer, in the order answered."""
    return [done_id(d) for d in await errands.untold(hearer, limit)]


async def told(errands: Errands, *ids: int) -> None:
    await errands.told(tuple(ids))


# --- the world -----------------------------------------------------------------------------------------------------


@dataclass
class World:
    url: str
    errands: Errands
    hid: int
    asker: int
    mate: int
    conv: int
    other_hid: int
    other_person: int
    other_conv: int

    def turn(self, visibility: str = "shared") -> int:
        """A new person turn by the asker, with this visibility."""
        return new_turn(self.url, self.hid, self.conv, self.asker, visibility)

    async def owe(self, source: str = HOUSE, visibility: str = "shared") -> int:
        return await self.errands.owe(self.hid, self.asker, self.conv, self.turn(visibility), source)

    async def owed_claimed(self, source: str = HOUSE, visibility: str = "shared") -> tuple[int, int]:
        """An errand owed and claimed once: its id and the attempt (1) it runs at."""
        eid = await self.owe(source, visibility)
        got = await claim(self.errands, (source,))
        assert got == eid
        return eid, attempts_of(self.url, eid)


    async def finished(self, text: str, visibility: str = "shared") -> int:
        """An errand owed with this visibility, claimed, run and finished with `text`."""
        eid, attempt = await self.owed_claimed(visibility=visibility)
        await self.errands.finish(eid, attempt, text)
        return eid


def new_conversation(url: str, hid: int, person_id: int) -> int:
    cid = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (hid,)))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                     "VALUES (%s, %s, %s)", (cid, hid, person_id))
    return cid


def new_turn(url: str, hid: int, conv: int, speaker: int, visibility: str = "shared") -> int:
    return int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                           "VALUES (%s, %s, 'person', %s, 'put it on the list', %s) RETURNING id",
                      (conv, hid, speaker, visibility)))


def make_world(url: str, database: Database) -> World:
    hid = household(url, "home")
    asker = person(url, hid, "asker")
    mate = person(url, hid, "mate")
    other_hid = household(url, "elsewhere")
    other_person = person(url, other_hid, "stranger")
    return World(url, make(database), hid, asker, mate, new_conversation(url, hid, asker), other_hid, other_person,
                 new_conversation(url, other_hid, other_person))


@asynccontextmanager
async def opened(url: str) -> AsyncGenerator[World]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield make_world(url, database)
    finally:
        await database.close()


def scenario(url: str, body: Any) -> None:
    """Run `body(world)` against a fresh world on this database."""

    async def go() -> None:
        async with opened(url) as w:
            await body(w)

    run(go())


# --- raw rows ---------------------------------------------------------------------------------------------------


def row(url: str, errand: int) -> dict[str, Any]:
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute("SELECT * FROM errands WHERE id = %s", (errand,))
        names = [c.name for c in cur.description or ()]
        found = cur.fetchone()
    assert found is not None, f"no errand {errand}"
    return dict(zip(names, found, strict=True))


def count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM errands"))


def attempts_of(url: str, errand: int) -> int:
    return int(scalar(url, "SELECT attempts FROM errands WHERE id = %s", (errand,)))


def state_of(url: str, errand: int) -> str:
    return str(scalar(url, "SELECT state FROM errands WHERE id = %s", (errand,)))


def age_created(url: str, errand: int, seconds: float) -> None:
    """Move the errand's creation `seconds` into the past."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE errands SET created_at = created_at - make_interval(secs => %s) WHERE id = %s",
                     (seconds, errand))


def age_claimed(url: str, errand: int, seconds: float) -> None:
    """Move the errand's claim `seconds` into the past."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE errands SET claimed_at = claimed_at - make_interval(secs => %s) WHERE id = %s",
                     (seconds, errand))


def seconds_since(url: str, errand: int, column: str) -> float:
    """How long ago the errand's `created_at`, `claimed_at`, `finished_at` or `told_at` was, by the database's clock."""
    assert column in ("created_at", "claimed_at", "finished_at", "told_at")
    query = f"SELECT extract(epoch FROM clock_timestamp() - {column}) FROM errands WHERE id = %s"
    return float(scalar(url, query, (errand,)))


def insert_errand(url: str, *, household_id: int, asker_id: int, conversation_id: int, turn_id: int,
                  source: str = HOUSE, state: str = "due", visibility: str = "shared", attempts: int = 0,
                  reason: str | None = None, result: str | None = None) -> int:
    """An errands row written directly, so the database's own constraints are what answer."""
    return int(scalar(url, "INSERT INTO errands (household_id, asker_id, conversation_id, turn_id, source, state, "
                           "attempts, reason, visibility, result) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                      (household_id, asker_id, conversation_id, turn_id, source, state, attempts, reason,
                       visibility, result)))


def age_told(url: str, errand: int, seconds: float) -> None:
    """Move the errand's `told_at` `seconds` into the past."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE errands SET told_at = told_at - make_interval(secs => %s) WHERE id = %s",
                     (seconds, errand))
