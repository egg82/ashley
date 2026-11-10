"""The open screens in Postgres: a screen counts while it is beating and not once it closes or goes quiet, and the rows
dead pods left behind are removed by the next opening."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from ashley.db.pool import PoolDatabase
from ashley.live.postgres_screens import LEFT_BEHIND_S, PostgresScreens
from ashley.live.screens import Screens, ScreensUnavailable
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar


@asynccontextmanager
async def stores(url: str) -> AsyncGenerator[Screens]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresScreens(db)
    finally:
        await db.close()


def test_an_unreachable_database_raises_the_services_own_error(db_url: str) -> None:
    async def go() -> None:
        db = PoolDatabase(unreachable_conninfo(), connect_timeout_s=0.5)
        with pytest.raises(ScreensUnavailable):
            await PostgresScreens(db).looking(1, 60)
    run(go())


def test_a_screen_counts_while_it_is_beating_and_not_after_it_closes_or_goes_quiet(db_url: str) -> None:
    home = household(db_url)
    alana, sam = person(db_url, home, "Alana"), person(db_url, home, "Sam")

    async def go() -> None:
        async with stores(db_url) as screens:
            first, second = await screens.opened(home, alana), await screens.opened(home, alana)
            assert await screens.looking(alana, 60) and not await screens.looking(sam, 60)
            await screens.closed(first)
            assert await screens.looking(alana, 60)   # the other is still open
            scalar(db_url, "WITH u AS (UPDATE live_screens SET seen_at = now() - interval '2 minutes' WHERE id = %s "
                           "RETURNING 1) SELECT count(*) FROM u", (second,))
            assert not await screens.looking(alana, 60) and await screens.looking(alana, 300)
            await screens.beat(second)
            assert await screens.looking(alana, 60)
            await screens.closed(second)
            assert not await screens.looking(alana, 60)
    run(go())


def test_rows_left_by_dead_pods_are_removed_by_the_next_opening_and_current_ones_are_not(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def go() -> None:
        async with stores(db_url) as screens:
            dead, live = await screens.opened(home, alana), await screens.opened(home, alana)
            scalar(db_url, "WITH u AS (UPDATE live_screens SET seen_at = now() - make_interval(secs => %s) "
                           "WHERE id = %s RETURNING 1) SELECT count(*) FROM u", (LEFT_BEHIND_S + 60, dead))
            await screens.opened(home, alana)
            ids = scalar(db_url, "SELECT coalesce(json_agg(id ORDER BY id), '[]') FROM live_screens")
            assert dead not in ids and live in ids and len(ids) == 2
    run(go())
