"""Settling claims over a real database: a claim is unsettled until settled, `unsettled` lists the claims made since a
time that were never settled with their channels, settling twice or settling what was never claimed changes nothing,
and a pruned claim is gone from both."""

from datetime import UTC, datetime, timedelta

from contract.conversations_support import db_now, run
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from discord_support import seen_store

LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def test_a_claim_is_unsettled_until_it_is_settled(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            await seen.claim(10, 1)
            await seen.claim(20, 2)
            assert await seen.unsettled(LONG_AGO) == {10: 1, 20: 2}
            await seen.settle(10)
            await seen.settle(10)
            await seen.settle(99)
            assert await seen.unsettled(LONG_AGO) == {20: 2}
            assert await seen.claim(10, 1) is False, "settling is not unclaiming"

    run(scenario())


def test_unsettled_leaves_out_claims_made_before_since(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            await seen.claim(10, 1)
            assert await seen.unsettled(db_now(db_url) + timedelta(days=1)) == {}

    run(scenario())


def test_a_pruned_claim_is_neither_unsettled_nor_claimed(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            await seen.claim(10, 1)
            await seen.prune(db_now(db_url) + timedelta(days=1))
            assert await seen.unsettled(LONG_AGO) == {}

    run(scenario())
