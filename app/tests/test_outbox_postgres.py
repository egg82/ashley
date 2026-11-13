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
from ashley.errands.errands import Errands
from ashley.errands.postgres import PostgresErrands
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar

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
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.1)
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


def asked(url: str, hid: int, cid: int, speaker: int | None, visibility: str = "shared") -> int:
    return int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                           "VALUES (%s, %s, 'person', %s, 'is it dry', %s) RETURNING id", (cid, hid, speaker, visibility)))


async def untold(url: str, who: int, owner_only: bool = True) -> list[str]:
    database = PoolDatabase(url)
    await database.open()
    try:
        return [d.result for d in await PostgresErrands(database).untold(who, 5, owner_only)]
    finally:
        await database.close()


def test_a_stale_held_answer_is_kept_for_the_asker_and_told_once(db_url: str) -> None:
    hid = household(db_url)
    who = person(db_url, hid)
    cid = conversation(db_url, hid)
    said = asked(db_url, hid, cid, who)

    async def scenario() -> None:
        async with outbox_on(db_url, stale_s=60) as outbox:
            made = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "It is dry."))
            scalar(db_url, "UPDATE outbox SET answers = %s WHERE id = %s RETURNING id", (said, made))
            age(db_url, made, 120)
            assert await outbox.take("device:") == []
        assert await untold(db_url, who) == ["It is dry."]
        database = PoolDatabase(db_url)
        await database.open()
        try:
            errands: Errands = PostgresErrands(database)
            (held,) = await errands.untold(who, 5)
            await errands.told([held.id])
            assert await errands.untold(who, 5) == ()
        finally:
            await database.close()

    run(scenario())


def test_what_is_not_a_held_answer_is_not_kept(db_url: str) -> None:
    hid = household(db_url)
    who = person(db_url, hid)
    cid = conversation(db_url, hid)
    known = asked(db_url, hid, cid, who)
    unknown = asked(db_url, hid, cid, None)

    async def scenario() -> None:
        async with outbox_on(db_url, stale_s=60) as outbox:
            rows = [
                (await outbox.add(hid, "device:3", Outbound(cid, "spoken", "fresh")), known, 5),
                (await outbox.add(hid, "device:3", Outbound(cid, "spoken", "no turn named")), None, 120),
                (await outbox.add(hid, "device:3", Outbound(cid, "spoken", "")), known, 120),
                (await outbox.add(hid, "device:3", Outbound(cid, "spoken", "no one to tell")), unknown, 120),
            ]
            for oid, turn, secs in rows:
                scalar(db_url, "UPDATE outbox SET answers = %s WHERE id = %s RETURNING id", (turn, oid))
                age(db_url, oid, secs)
            assert [g.outbound.body for g in await outbox.take("device:")] == ["fresh"]
        assert await untold(db_url, who) == []

    run(scenario())


def test_a_held_answer_to_a_private_ask_is_heard_by_its_owner_alone(db_url: str) -> None:
    hid = household(db_url)
    who = person(db_url, hid, "asker")
    other = person(db_url, hid, "other")
    cid = conversation(db_url, hid)
    said = asked(db_url, hid, cid, who, "private")

    async def scenario() -> None:
        async with outbox_on(db_url, stale_s=60) as outbox:
            made = await outbox.add(hid, "device:3", Outbound(cid, "spoken", "Private."))
            scalar(db_url, "UPDATE outbox SET answers = %s WHERE id = %s RETURNING id", (said, made))
            age(db_url, made, 120)
            await outbox.take("device:")
        assert await untold(db_url, other) == []
        assert await untold(db_url, who, owner_only=False) == []
        assert await untold(db_url, who) == ["Private."]

    run(scenario())
