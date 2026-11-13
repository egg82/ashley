"""The remarks store over a real database (`ashley.channels.postgres_remarks.PostgresRemarks`): a source is claimed
once per household; `before` counts a person's remarks since a time that went out or are unsettled, and lists the
household's sent lines since a time; `settle` happens once; `prune` deletes older claims; an unreachable database
raises RemarksUnavailable. Times are the caller's, so the windows are arithmetic."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from ashley.channels.postgres_remarks import PostgresRemarks
from ashley.channels.remarks import RemarksUnavailable
from ashley.db.pool import PoolDatabase
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import household, person, run
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
DAY = NOW - timedelta(days=1)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


@asynccontextmanager
async def store(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[PostgresRemarks]:
    database = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await database.open()
    try:
        yield PostgresRemarks(database)
    finally:
        await database.close()


def test_a_source_is_claimed_once_per_household(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    alana, bea = person(db_url, home), person(db_url, other)

    async def scenario() -> None:
        async with store(db_url) as remarks:
            assert await remarks.claim(home, alana, "discord:1", NOW) is True
            assert await remarks.claim(home, alana, "discord:1", NOW) is False
            assert await remarks.claim(other, bea, "discord:1", NOW) is True

    run(scenario())


def test_before_counts_sent_and_unsettled_remarks_of_the_person_since_the_count_start(db_url: str) -> None:
    home = household(db_url)
    alana, cass = person(db_url, home, "alana"), person(db_url, home, "cass")

    async def scenario() -> None:
        async with store(db_url) as remarks:
            for source, who, at, line in [("sent", alana, NOW, "f1"), ("quiet", alana, NOW, None),
                                          ("old", alana, DAY - timedelta(seconds=1), "f2"),
                                          ("theirs", cass, NOW, "f3")]:
                await remarks.claim(home, who, source, at)
                await remarks.settle(home, source, line)
            await remarks.claim(home, alana, "running", NOW)
            got = await remarks.before(home, alana, DAY, LONG_AGO)
            assert got.sent == 2, "the sent one and the unsettled one; not the quiet, old or other person's"
            assert sorted(got.said) == ["f1", "f2", "f3"], "lines are the household's, any person's"
            assert sorted((await remarks.before(home, alana, DAY, DAY)).said) == ["f1", "f3"]

    run(scenario())


def test_a_remark_is_settled_once(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with store(db_url) as remarks:
            await remarks.claim(home, alana, "discord:1", NOW)
            await remarks.settle(home, "discord:1", None)
            await remarks.settle(home, "discord:1", "late")
            got = await remarks.before(home, alana, DAY, LONG_AGO)
            assert got.sent == 0 and got.said == ()

    run(scenario())


def test_prune_deletes_claims_made_before_the_time_only(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with store(db_url) as remarks:
            await remarks.claim(home, alana, "old", DAY - timedelta(seconds=1))
            await remarks.claim(home, alana, "new", NOW)
            assert await remarks.prune(DAY) == 1
            assert await remarks.claim(home, alana, "old", NOW) is True
            assert await remarks.claim(home, alana, "new", NOW) is False

    run(scenario())


def test_an_unreachable_database_raises_remarks_unavailable() -> None:
    async def scenario() -> None:
        async with store(unreachable_conninfo(), connect_timeout_s=0.1) as remarks:
            with pytest.raises(RemarksUnavailable):
                await remarks.claim(1, 1, "discord:1", NOW)

    run(scenario())
