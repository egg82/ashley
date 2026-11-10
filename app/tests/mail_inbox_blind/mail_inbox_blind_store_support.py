"""A real `PostgresWatches` on a migrated database for the `Later` tests, and raw SQL to read and age its rows.

  G8  The store is `PostgresWatches(database, config)` with a `WatchesConfig`, and an `Arm` is built by keyword with the
      fields of `ashley.watches.model.Arm`; both as the existing Watches store does."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from ashley.db.pool import PoolDatabase
from ashley.watches.config import CONFIG
from ashley.watches.model import Arm
from ashley.watches.postgres import PostgresWatches
from contract.conversations_support import household, person, scalar
from mail_inbox_blind_support import TRACK, run

RETRY_S = 600
INTERVAL_S = 30
ITEMS = {"m1": {"from": "a", "subject": "s", "unread": True, "labels": ""}}


@dataclass
class Store:
    url: str
    store: PostgresWatches
    household_id: int
    person_id: int

    async def armed_due(self) -> tuple[int, int]:
        """A `mail_inbox` watch with a baseline, made due now: its id and version."""
        arm = Arm(household_id=self.household_id, person_id=self.person_id, kind="mail_inbox", target="box@example.test",
                  label="inbox", bench_id=None, armed_by="ashley", track=TRACK, when=CONFIG.kinds["mail_inbox"].when,
                  until=None, tools=None, interval_s=INTERVAL_S, expires_at=datetime.now(UTC) + timedelta(hours=24),
                  baseline=ITEMS)
        watch_id = int((await self.store.arm(arm)).id)
        self.make_due(watch_id)
        return watch_id, int(self.row(watch_id)["version"])

    def row(self, watch_id: int) -> dict[str, Any]:
        with psycopg.connect(self.url, autocommit=True) as conn:
            cur = conn.execute(b"SELECT * FROM watches WHERE id = %s", (watch_id,))
            names = [c.name for c in cur.description or ()]
            found = cur.fetchone()
        assert found is not None
        return dict(zip(names, found, strict=True))

    def wakes(self, watch_id: int) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM wakes WHERE watch_id = %s", (watch_id,)))

    def make_due(self, watch_id: int) -> None:
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(b"UPDATE watches SET next_check_at = clock_timestamp() - interval '5 seconds' WHERE id = %s",
                         (watch_id,))

    def seconds_until_next(self, watch_id: int) -> float:
        return float(scalar(self.url, "SELECT extract(epoch FROM next_check_at - clock_timestamp()) FROM watches "
                                      "WHERE id = %s", (watch_id,)))


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
        config = replace(CONFIG, fail_after=3, retry_s=RETRY_S, keep_s=3600.0)
        yield Store(url, PostgresWatches(database, config), hid, person(url, hid, "owner"))
    finally:
        await database.close()
