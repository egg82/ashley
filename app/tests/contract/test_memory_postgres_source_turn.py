"""A fact is stored with the turn it came from, of its own conversation."""

from datetime import UTC, datetime

import pytest
from ashley.memory.model import Add, NewFact
from ashley.memory.postgres import PostgresMemory

from conversations_support import household, person, run
from memory_support import conversation, pool, say

AT = datetime(2026, 3, 1, tzinfo=UTC)


def fact(owner: int | None, text: str, turn: int | None, visibility: str = "shared") -> NewFact:
    assert visibility in ("shared", "discreet", "private")
    return NewFact(owner, owner, visibility, False, "preference", False, text, turn)


def test_a_fact_cannot_name_a_turn_of_another_conversation(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "alana")
    talk, other = conversation(db_url, home), conversation(db_url, home)
    (elsewhere,) = say(db_url, other, "hello", speaker=alana)

    async def scenario() -> None:
        async with pool(db_url) as db:
            with pytest.raises(ValueError):
                await PostgresMemory(db).apply(home, talk, [Add(fact(alana, "Alana likes tea", elsewhere))], AT)

    run(scenario())

