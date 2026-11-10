"""The claim store over a real database: a message is claimed by exactly one caller however many ask, `last` reports the
greatest claimed id per channel among claims made since a time, `prune` deletes older claims (which can then be claimed
again), and a database that cannot be written raises SeenUnavailable."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ashley.channels.discord.seen import SeenUnavailable
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import db_now, run, scalar
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from discord_support import execute, seen_store

BIG = 1_234_567_890_123_456_789      # a real snowflake does not fit 32 bits
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def test_a_message_is_claimed_by_the_first_caller_only_whatever_its_channel(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            assert await seen.claim(BIG, 10) is True
            assert await seen.claim(BIG, 10) is False
            assert await seen.claim(BIG, 11) is False, "the message id is the claim"
            assert await seen.claim(BIG + 1, 10) is True

    run(scenario())


def test_concurrent_claimers_in_separate_sessions_never_both_win(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as a, seen_store(db_url) as b:
            same = await asyncio.gather(*[(a if i % 2 else b).claim(BIG, 10) for i in range(12)])
            assert same.count(True) == 1 and same.count(False) == 11
            ids = range(BIG + 100, BIG + 120)
            both = await asyncio.gather(*[s.claim(i, 10) for i in ids for s in (a, b)])
            assert both.count(True) == len(ids), "each of twenty messages won exactly once"

    run(scenario())


def test_last_is_the_greatest_claimed_id_per_channel_among_claims_made_since(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            assert await seen.last(LONG_AGO) == {}
            for message_id, channel in [(30, 1), (10, 1), (20, 2)]:
                await seen.claim(message_id, channel)
            assert await seen.last(LONG_AGO) == {1: 30, 2: 20}
            assert await seen.last(db_now(db_url) + timedelta(days=1)) == {}

    run(scenario())


def test_last_leaves_out_claims_made_before_since_even_when_their_ids_are_greater(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            await seen.claim(100, 7)
            await seen.claim(50, 9)
            await asyncio.sleep(0.05)
            since = db_now(db_url)
            await asyncio.sleep(0.05)
            await seen.claim(2, 7)
            await seen.claim(3, 8)
            assert await seen.last(since) == {7: 2, 8: 3}, "channel 9 has no claim since, channel 7's greatest is 2"
            assert await seen.last(LONG_AGO) == {7: 100, 8: 3, 9: 50}

    run(scenario())


def test_prune_deletes_claims_made_before_a_time_and_counts_them(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            await seen.claim(1, 7)
            await seen.claim(2, 7)
            await asyncio.sleep(0.05)
            cut = db_now(db_url)
            await asyncio.sleep(0.05)
            await seen.claim(3, 7)
            assert await seen.prune(LONG_AGO) == 0
            assert await seen.prune(cut) == 2
            assert await seen.last(LONG_AGO) == {7: 3}
            assert await seen.claim(1, 7) is True, "a pruned claim can be made again"
            assert await seen.claim(3, 7) is False, "and a kept one cannot"
            assert await seen.prune(db_now(db_url) + timedelta(days=1)) == 2
            assert await seen.last(LONG_AGO) == {}

    run(scenario())


def test_last_includes_and_prune_keeps_a_claim_made_exactly_at_the_boundary(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as seen:
            await seen.claim(5, 7)
            execute(db_url, "UPDATE discord_seen SET claimed_at = '2024-01-01T00:00:00Z' WHERE message_id = 5")
            edge = datetime(2024, 1, 1, tzinfo=UTC)
            assert await seen.last(edge) == {7: 5}
            assert await seen.prune(edge) == 0
            assert await seen.last(LONG_AGO) == {7: 5}

    run(scenario())


def test_a_database_that_cannot_be_written_raises_seen_unavailable(db_url: str) -> None:
    async def scenario() -> None:
        async with seen_store(db_url) as before:
            assert await before.claim(1, 7) is True, "control: the database was writable"
        name = scalar(db_url, "SELECT current_database()")
        execute(db_url, f'ALTER DATABASE "{name}" SET default_transaction_read_only = on')
        async with seen_store(db_url) as seen:
            with pytest.raises(SeenUnavailable):
                await seen.claim(2, 7)

    run(scenario())


def test_an_unreachable_database_raises_seen_unavailable() -> None:
    async def scenario() -> None:
        async with seen_store(unreachable_conninfo(), connect_timeout_s=0.5) as seen:
            with pytest.raises(SeenUnavailable):
                await seen.claim(1, 7)

    run(scenario())
