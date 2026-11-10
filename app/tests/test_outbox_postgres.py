"""The outbox over a real database: `add` answers the new id; `take` removes and returns every waiting reply whose
thread starts with the prefix, oldest first, each to one taker however many ask at once; replies older than `stale_s`
are removed and not returned; other prefixes are untouched; an unreachable database is OutboxUnavailable."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
import pytest
from ashley.channels.model import Outbound
from ashley.channels.outbox import Later, Outbox, OutboxUnavailable
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations import policy
from ashley.db.pool import PoolDatabase
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, run, scalar

STALE_S = 60.0


@asynccontextmanager
async def outbox_on(url: str, stale_s: float = STALE_S) -> AsyncGenerator[Outbox]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresOutbox(database, stale_s, policy.load())
    finally:
        await database.close()


def conversation(url: str, household_id: int) -> int:
    return int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                      (household_id,)))


def waiting(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM outbox"))


def age(url: str, outbox_id: int, seconds: int) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE outbox SET created_at = clock_timestamp() - make_interval(secs => %s) WHERE id = %s",
                     (seconds, outbox_id))


def body(n: int = 0) -> Outbound:
    return Outbound(0, "text", f"reply {n}")


def test_add_answers_the_new_id_and_take_returns_the_reply_whole(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            first = await outbox.add(hid, "discord:10", Outbound(cid, "text", "It is dry."))
            second = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "It is dry."))
            assert first != second
            (got,) = await outbox.take("discord:")
            assert (got.id, got.household_id, got.thread) == (first, hid, "discord:10")
            assert got.outbound == Outbound(cid, "text", "It is dry.")
            assert 0 <= got.age_ms < 10_000
            (other,) = await outbox.take("device:")
            assert other.outbound == Outbound(cid, "spoken", "It is dry.") and other.id == second

    run(scenario())


def test_take_removes_what_it_returns(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            await outbox.add(hid, "device:3", Outbound(cid, "spoken", "once"))
            assert len(await outbox.take("device:")) == 1
            assert await outbox.take("device:") == []

    run(scenario())
    assert waiting(db_url) == 0


def test_take_on_an_empty_outbox_is_empty(db_url: str) -> None:
    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            assert await outbox.take("device:") == []

    run(scenario())


def test_replies_come_oldest_first(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            ids = [await outbox.add(hid, f"device:{n}", Outbound(cid, "spoken", f"r{n}")) for n in (9, 2, 5, 1)]
            age(db_url, ids[0], 30)
            age(db_url, ids[1], 20)
            age(db_url, ids[2], 10)
            got = await outbox.take("device:")
            assert [g.id for g in got] == ids
            assert [g.outbound.body for g in got] == ["r9", "r2", "r5", "r1"]
            assert [g.age_ms for g in got] == sorted((g.age_ms for g in got), reverse=True)

    run(scenario())


def test_only_threads_starting_with_the_prefix_are_taken_and_the_rest_wait(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            for thread in ("device:3", "device:7:kitchen", "discord:10", "xdevice:3"):
                await outbox.add(hid, thread, Outbound(cid, "text", thread))
            got = await outbox.take("device:")
            assert sorted(g.thread for g in got) == ["device:3", "device:7:kitchen"]
            assert waiting(db_url) == 2
            (rest,) = await outbox.take("discord:")
            assert rest.thread == "discord:10"
            assert waiting(db_url) == 1

    run(scenario())


@pytest.mark.parametrize("prefix", ["dev_ce:", "%", "device:%", "_"])
def test_a_prefix_is_literal_text_not_a_pattern(db_url: str, prefix: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            await outbox.add(hid, "device:3", Outbound(cid, "text", "x"))
            assert await outbox.take(prefix) == []
            assert len(await outbox.take("device:")) == 1, "control: the literal prefix does take it"

    run(scenario())


def test_replies_past_stale_s_are_removed_and_not_returned(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url, stale_s=60) as outbox:
            old = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "old"))
            fresh = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "fresh"))
            age(db_url, old, 120)
            got = await outbox.take("device:")
            assert [g.id for g in got] == [fresh]

    run(scenario())
    assert waiting(db_url) == 0


def test_a_reply_just_inside_stale_s_is_delivered(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url, stale_s=60) as outbox:
            made = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "late"))
            age(db_url, made, 45)
            (got,) = await outbox.take("device:")
            assert got.id == made and 45_000 <= got.age_ms < 55_000

    run(scenario())


def test_a_longer_stale_s_delivers_what_a_shorter_one_drops(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url, stale_s=600) as outbox:
            made = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "slow"))
            age(db_url, made, 120)
            assert [g.id for g in await outbox.take("device:")] == [made]

    run(scenario())


def test_two_takers_never_get_the_same_reply(db_url: str) -> None:
    hid = household(db_url)
    cid = conversation(db_url, hid)

    async def scenario() -> None:
        async with outbox_on(db_url) as outbox:
            ids = [await outbox.add(hid, f"device:{n}", Outbound(cid, "spoken", f"r{n}")) for n in range(40)]
            batches: list[list[Later]] = await asyncio.gather(*(outbox.take("device:") for _ in range(4)))
            taken = [g.id for batch in batches for g in batch]
            assert sorted(taken) == sorted(ids), "every reply taken, none twice"

    run(scenario())
    assert waiting(db_url) == 0


def test_an_unreachable_database_is_outbox_unavailable() -> None:
    async def scenario() -> None:
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.3)
        await database.open()
        try:
            outbox = PostgresOutbox(database, STALE_S, policy.load())
            with pytest.raises(OutboxUnavailable):
                await outbox.take("device:")
            with pytest.raises(OutboxUnavailable):
                await outbox.add(1, "device:3", body())
        finally:
            await database.close()

    run(scenario())
