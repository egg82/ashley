"""The Postgres claim store: a claim is unsettled until settled, and `unsettled` reads a window."""

from datetime import UTC, datetime, timedelta

from contract.conversations_support import run
from discord_support import seen_store

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def test_a_claim_is_unsettled_until_it_is_settled(db_url: str) -> None:
    async def go() -> None:
        async with seen_store(db_url) as seen:
            assert await seen.claim(10, 1) and await seen.claim(11, 1) and await seen.claim(20, 2)
            assert await seen.unsettled(LONG_AGO) == {10: 1, 11: 1, 20: 2}
            await seen.settle(11)
            assert await seen.unsettled(LONG_AGO) == {10: 1, 20: 2}
            await seen.settle(11)
            await seen.settle(999)
            assert await seen.unsettled(LONG_AGO) == {10: 1, 20: 2}
            assert await seen.claim(10, 1) is False and await seen.claim(11, 1) is False
            assert await seen.last(LONG_AGO) == {1: 11, 2: 20}, "a settled claim is still the last claimed"
            assert await seen.claim(999, 3), "settling a message never claimed claimed nothing"

    run(go())


def test_unsettled_reads_only_claims_made_in_its_window(db_url: str) -> None:
    async def go() -> None:
        async with seen_store(db_url) as seen:
            assert await seen.claim(10, 1)
            assert await seen.unsettled(datetime.now(UTC) + timedelta(hours=1)) == {}
            assert await seen.unsettled(datetime.now(UTC) - timedelta(hours=1)) == {10: 1}

    run(go())
