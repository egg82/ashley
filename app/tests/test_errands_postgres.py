"""The errands table through `PostgresErrands`: one errand per turn, a claim that takes the oldest due errand of an
answering source once, a settle that needs the attempt it was claimed at, the sweep's two verdicts, and `untold`
filtered by who may hear."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from ashley.db.pool import PoolDatabase
from ashley.errands.errands import Errands, ErrandsUnavailable, NullErrands
from ashley.errands.postgres import PostgresErrands
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[Errands]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresErrands(db)
    finally:
        await db.close()


def turn(url: str, home: int, who: int, visibility: str = "shared") -> tuple[int, int]:
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    made = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                           "VALUES (%s, %s, 'person', %s, 'x', %s) RETURNING id", (conversation, home, who, visibility)))
    return conversation, made


def test_owe_is_once_per_turn_and_claim_takes_it_once(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)
    conversation, made = turn(db_url, home, who)

    async def go() -> None:
        async with store(db_url) as errands:
            first = await errands.owe(home, who, conversation, made, "house")
            assert await errands.owe(home, who, conversation, made, "house") == first
            assert await errands.claim(["search"], 60) is None
            got = await errands.claim(["house"], 60)
            assert got is not None and (got.id, got.attempt) == (first, 1)
            assert await errands.claim(["house"], 60) is None
            assert await errands.release(first, 2, 3) == "running"
            assert await errands.release(first, 1, 3) == "due"
            again = await errands.claim(["house"], 60)
            assert again is not None and again.attempt == 2
            assert await errands.release(first, 2, 2) == "given_up"
    run(go())
    assert scalar(db_url, "SELECT reason FROM errands") == "attempts"


def test_finish_then_untold_respects_visibility_and_told_hides_it(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)
    ids: list[int] = []

    async def go() -> None:
        async with store(db_url) as errands:
            for visibility in ("shared", "private"):
                conversation, made = turn(db_url, home, who, visibility)
                ids.append(await errands.owe(home, who, conversation, made, "house"))
                got = await errands.claim(["house"], 60)
                assert got is not None
                await errands.finish(got.id, got.attempt, f"did {visibility}")
            assert [d.result for d in await errands.untold(who, 5)] == ["did shared", "did private"]
            assert [d.result for d in await errands.untold(who, 5, owner_only=False)] == ["did shared"]
            assert await errands.untold(who + 1000, 5) == ()
            await errands.told(ids)
            assert await errands.untold(who, 5) == ()
    run(go())


def test_sweep_gives_up_the_stale_and_the_unclaimed(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)
    a, b = turn(db_url, home, who), turn(db_url, home, who)

    async def go() -> None:
        async with store(db_url) as errands:
            await errands.owe(home, who, *a, "house")
            await errands.claim(["house"], 60)
            await errands.owe(home, who, *b, "house")
            scalar(db_url, "UPDATE errands SET claimed_at = now() - interval '1 hour', "
                           "created_at = now() - interval '2 hours' WHERE state = 'running' RETURNING 1")
            scalar(db_url, "UPDATE errands SET created_at = now() - interval '2 hours' WHERE state = 'due' RETURNING 1")
            counts = await errands.sweep(600, 3600)
            assert (counts.interrupted, counts.expired) == (1, 1)
    run(go())


def test_the_null_object_raises() -> None:
    async def go() -> None:
        with pytest.raises(ErrandsUnavailable):
            await NullErrands().claim(["house"], 1)
    run(go())
