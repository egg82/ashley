"""Shared helpers for the blind tests of the sort (`decisions.md`, "The inbox watch and the sort", build part 8): the
constants, the `Arm` and `Watch` records with the fields a watch gains, and the real `PostgresWatches` store on a
migrated database for the standing watch's expiry, driven through the real `watches` job by a scripted kind.

The implementation did not exist when these were written. Every guess beyond the spec is a numbered G; the list, with
the spec phrase each rests on, is `~/scratch/ashley/mail/sort-blind/assumptions.txt`. A reconciler changes a helper
here, never a test.

  G1  `brief` and `standing` are fields of both `Arm` and `Watch`, built by keyword: `brief` a `str | None`
      (default None), `standing` a `bool` (default False).
  G2  A standing watch's `hours` is the span it was armed for: `expires_at - armed_at` at arming. A read that succeeded
      (`Baseline`, `Quiet` or `Woke`) sets `expires_at` to now + `hours`; no other check moves it."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.watches import job
from ashley.watches.config import CONFIG
from ashley.watches.kinds import Kind, Registry
from ashley.watches.model import Arm, Armed, Read, Watch
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from contract.conversations_support import household, person, scalar

KIND = "mail_inbox"
ADDRESS = "zs-box-5512@example.test"
OTHER_ADDRESS = "zs-other-8830@example.test"
BRIEF = "zs-brief-6643 sort the inbox for the school mail"
TRACK = ("from", "subject", "unread", "labels")
ITEMS = {"m1": {"from": "a", "subject": "s", "unread": True, "labels": ""}}
MORE = {**ITEMS, "m2": {"from": "b", "subject": "t", "unread": True, "labels": ""}}
TICK = replace(CONFIG, tick_s=0.01, batch=10, read_timeout_s=0.5, fail_after=3, retry_s=60.0, keep_s=3600.0)


def run(scenario: Coroutine[Any, Any, None], limit: float = 20.0) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, limit)

    asyncio.run(bounded())


class Scripted(Kind):
    """A `mail_inbox` kind whose read of every watch is `answer`."""

    name = KIND
    empty_is_absent = False

    def __init__(self, answer: Read) -> None:
        self.answer = answer

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        return {w.id: self.answer for w in group}


def arm_of(household_id: int, person_id: int, *, hours: float = 24.0, standing: bool = False,
           brief: str | None = None, target: str = ADDRESS,
           baseline: Mapping[str, Mapping[str, Any]] | None = ITEMS) -> Arm:
    """An `Arm` of a `mail_inbox` watch on `target` for `hours`, with the kind's own default `when`."""
    return Arm(household_id=household_id, person_id=person_id, kind=KIND, target=target, label="inbox", bench_id=None,
               armed_by="ashley", track=TRACK, when=CONFIG.kinds[KIND].when, until=None, tools=("mail_label",),
               interval_s=CONFIG.kinds[KIND].interval_s, expires_at=datetime.now(UTC) + timedelta(hours=hours),
               baseline=None if baseline is None else {k: dict(v) for k, v in baseline.items()},
               brief=brief, standing=standing)


@dataclass
class Store:
    url: str
    store: PostgresWatches
    household_id: int
    person_id: int

    async def arm_for(self, **over: Any) -> Armed:
        """Arm a watch (see `arm_of`) for this person."""
        return await self.store.arm(arm_of(self.household_id, self.person_id, **over))

    async def armed(self, **over: Any) -> int:
        """Arm a watch (see `arm_of`) and return its id."""
        return int((await self.arm_for(**over)).id)

    def row(self, watch_id: int) -> dict[str, Any]:
        with psycopg.connect(self.url, autocommit=True) as conn:
            cur = conn.execute(b"SELECT * FROM watches WHERE id = %s", (watch_id,))
            names = [c.name for c in cur.description or ()]
            found = cur.fetchone()
        assert found is not None
        return dict(zip(names, found, strict=True))

    def hours_left(self, watch_id: int) -> float:
        """Hours from now to the watch's `expires_at`."""
        return float(scalar(self.url, "SELECT extract(epoch FROM expires_at - clock_timestamp()) / 3600 FROM watches "
                                      "WHERE id = %s", (watch_id,)))

    def age(self, watch_id: int, hours: float) -> None:
        """`hours` have passed since the watch was armed and last read, and it is due."""
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(b"UPDATE watches SET armed_at = armed_at - make_interval(secs => %s), expires_at = expires_at - "
                         b"make_interval(secs => %s), next_check_at = clock_timestamp() - interval '5 seconds' "
                         b"WHERE id = %s", (hours * 3600, hours * 3600, watch_id))

    def due(self, watch_id: int) -> None:
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(b"UPDATE watches SET next_check_at = clock_timestamp() - interval '5 seconds' WHERE id = %s",
                         (watch_id,))

    async def tick(self, answer: Read) -> None:
        """One job tick, the real job over the real store, reading `answer` for every due watch."""
        await job.tick(TICK, Registry([Scripted(answer)]))


def scenario(url: str, body: Any) -> None:
    async def go() -> None:
        async with opened(url) as s:
            await body(s)

    run(go())


@asynccontextmanager
async def opened(url: str) -> AsyncGenerator[Store]:
    database = PoolDatabase(url)
    await database.open()
    try:
        hid = household(url, "home")
        store = PostgresWatches(database, TICK)
        services.register(Watches, store)
        yield Store(url, store, hid, person(url, hid, "owner"))
    finally:
        services.unregister(Watches)
        await database.close()
