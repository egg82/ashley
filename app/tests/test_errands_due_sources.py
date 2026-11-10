"""`Errands.due_sources` in Postgres: the distinct sources of due errands young enough to claim, and the Null Object."""

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


def asked(url: str, home: int, who: int) -> tuple[int, int]:
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    made = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                           "VALUES (%s, %s, 'person', %s, 'x', 'shared') RETURNING id", (conversation, home, who)))
    return conversation, made


def test_only_due_young_errands_name_their_source_once(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def go() -> None:
        async with store(db_url) as errands:
            assert await errands.due_sources(60) == frozenset()
            for source in ("house", "house", "search", "everyday"):
                conversation, made = asked(db_url, home, who)
                await errands.owe(home, who, conversation, made, source)
            assert await errands.due_sources(60) == {"house", "search", "everyday"}
            taken = await errands.claim(["everyday"], 60)
            assert taken is not None
            assert await errands.due_sources(60) == {"house", "search"}
            await errands.finish(taken.id, taken.attempt, "did it")
            assert await errands.due_sources(60) == {"house", "search"}
    run(go())
    scalar(db_url, "UPDATE errands SET created_at = now() - interval '2 hours' WHERE source = 'search' RETURNING 1")

    async def aged() -> None:
        async with store(db_url) as errands:
            assert await errands.due_sources(3600) == {"house"}
    run(aged())


def test_the_null_object_raises() -> None:
    async def go() -> None:
        with pytest.raises(ErrandsUnavailable):
            await NullErrands().due_sources(60)
    run(go())
