"""Contract 9 and 14's service half, blind, over a real database: her turn stores `spoken` in the same insert as her
text, only her turns may, an empty one is refused, and `Conversations.spoken` answers only for the household and thread
the turn is in and only within `within_s` of the database's clock."""

import asyncio
from collections.abc import Coroutine
from typing import Any

import psycopg
import pytest
from ashley.conversations.conversations import ConversationError, Conversations, ConversationsUnavailable
from ashley.conversations.model import Author, NewTurn, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from contract.conversations_support import POLICY, scalar, service
from pv_pg_support import Home, age, seed
from pv_pg_support import home as home

WORDS = "Mowchi is asleep, so I will keep it down."
CHAT = "person:{}:web"


def run[R](scenario: Coroutine[Any, Any, R]) -> R:
    return asyncio.run(asyncio.wait_for(scenario, 25))


def _alana_thread(home: Home) -> str:
    return CHAT.format(home.alana.id)


def test_c09_her_turn_stores_spoken_and_reads_it_back_beside_its_text(home: Home) -> None:
    made = seed(home.url, home.house, _alana_thread(home), home.alana.id, spoken=WORDS, text="Mowchi is asleep.")

    async def go() -> list[Turn]:
        async with service(home.url) as conversations:
            found = await conversations.get(made.conversation)
            assert found is not None
            return list(found.turns)

    person, hers = run(go())
    assert (person.author, person.spoken) == ("person", None)
    assert (hers.author, hers.text, hers.spoken) == ("ashley", "Mowchi is asleep.", WORDS)
    assert scalar(home.url, "SELECT spoken FROM turns WHERE id = %s", (made.turn,)) == WORDS


def test_c09_a_turn_built_without_spoken_has_none() -> None:
    assert NewTurn("ashley", "x").spoken is None


@pytest.mark.parametrize("author", ["person", "household"])
def test_c09_a_person_or_household_turn_with_spoken_is_refused_and_nothing_is_stored(home: Home,
                                                                                     author: Author) -> None:
    async def go() -> None:
        async with service(home.url) as conversations:
            talk = await conversations.for_thread(home.house, _alana_thread(home), "chat", [home.alana.id])
            speaker = home.alana.id if author == "person" else None
            bad = NewTurn(author, "hello", speaker, spoken="hello")
            with pytest.raises((ValueError, ConversationError)):
                await conversations.add_turn(talk.id, bad)

    run(go())
    assert scalar(home.url, "SELECT count(*) FROM turns") == 0


def test_c09_an_empty_spoken_on_her_turn_is_refused_and_nothing_is_stored(home: Home) -> None:
    async def go() -> None:
        async with service(home.url) as conversations:
            talk = await conversations.for_thread(home.house, _alana_thread(home), "chat", [home.alana.id])
            with pytest.raises((ValueError, ConversationError)):
                await conversations.add_turn(talk.id, NewTurn("ashley", "hello", spoken=""))

    run(go())
    assert scalar(home.url, "SELECT count(*) FROM turns") == 0


def test_c09_the_schema_itself_refuses_a_voice_on_a_person_turn_and_an_empty_one(home: Home) -> None:
    made = seed(home.url, home.house, _alana_thread(home), home.alana.id, spoken=WORDS)
    with psycopg.connect(home.url, autocommit=True) as conn:
        for turn_id, value in ((made.asked, WORDS), (made.turn, "")):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("UPDATE turns SET spoken = %s WHERE id = %s", (value, turn_id))
        conn.execute("UPDATE turns SET spoken = NULL WHERE id = %s", (made.turn,))
    assert scalar(home.url, "SELECT spoken IS NULL FROM turns WHERE id = %s", (made.turn,)) is True


def spoken_of(url: str, household_id: int, thread: str, turn_id: int, within_s: int = 120) -> str | None:
    async def go() -> str | None:
        async with service(url) as conversations:
            return await conversations.spoken(household_id, thread, turn_id, within_s)

    return run(go())


def test_spoken_is_the_turns_voice_for_its_own_household_and_thread(home: Home) -> None:
    thread = _alana_thread(home)
    made = seed(home.url, home.house, thread, home.alana.id, spoken=WORDS)
    assert spoken_of(home.url, home.house, thread, made.turn) == WORDS


def test_spoken_is_none_on_another_thread_even_in_the_same_household(home: Home) -> None:
    made = seed(home.url, home.house, _alana_thread(home), home.alana.id, spoken=WORDS)
    assert spoken_of(home.url, home.house, CHAT.format(home.sam.id), made.turn) is None
    assert spoken_of(home.url, home.house, "device:7", made.turn) is None
    assert spoken_of(home.url, home.house, _alana_thread(home), made.turn) == WORDS, "control: its own thread"


def test_spoken_is_none_for_another_household_even_on_the_same_thread_name(home: Home) -> None:
    mine = seed(home.url, home.house, "device:7", None, spoken=WORDS)
    assert spoken_of(home.url, home.house, "device:7", mine.turn) == WORDS
    theirs = seed(home.url, home.other_house, "device:7", None, spoken="theirs")
    assert spoken_of(home.url, home.other_house, "device:7", mine.turn) is None
    assert spoken_of(home.url, home.house, "device:7", theirs.turn) is None
    assert spoken_of(home.url, home.other_house, "device:7", theirs.turn) == "theirs"


def test_spoken_is_none_for_a_person_turn_a_turn_without_a_voice_and_a_missing_id(home: Home) -> None:
    thread = _alana_thread(home)
    voiced = seed(home.url, home.house, thread, home.alana.id, spoken=WORDS)
    plain = seed(home.url, home.house, thread, home.alana.id, spoken=None)
    assert spoken_of(home.url, home.house, thread, voiced.asked) is None
    assert spoken_of(home.url, home.house, thread, plain.turn) is None
    assert spoken_of(home.url, home.house, thread, plain.turn + 1000) is None
    assert spoken_of(home.url, home.house, thread, voiced.turn) == WORDS


def test_c14_spoken_expires_by_the_database_clock_at_within_s(home: Home) -> None:
    thread = _alana_thread(home)
    made = seed(home.url, home.house, thread, home.alana.id, spoken=WORDS)
    age(home.url, made.conversation, 100)
    assert spoken_of(home.url, home.house, thread, made.turn, within_s=120) == WORDS
    age(home.url, made.conversation, 30)
    assert spoken_of(home.url, home.house, thread, made.turn, within_s=120) is None
    assert spoken_of(home.url, home.house, thread, made.turn, within_s=600) == WORDS


def test_c14_the_window_is_the_argument_not_a_constant(home: Home) -> None:
    thread = _alana_thread(home)
    made = seed(home.url, home.house, thread, home.alana.id, spoken=WORDS)
    age(home.url, made.conversation, 10)
    assert spoken_of(home.url, home.house, thread, made.turn, within_s=5) is None
    assert spoken_of(home.url, home.house, thread, made.turn, within_s=15) == WORDS


def test_c14_the_text_outlives_the_voice(home: Home) -> None:
    thread = _alana_thread(home)
    made = seed(home.url, home.house, thread, home.alana.id, spoken=WORDS, text="Mowchi is asleep.")
    age(home.url, made.conversation, 10_000)

    async def go() -> list[Turn]:
        async with service(home.url) as conversations:
            found = await conversations.on_thread(home.house, thread)
            return [] if found is None else list(found.turns)

    assert ("Mowchi is asleep.", WORDS) in [(t.text, t.spoken) for t in run(go())]


def test_c15_spoken_with_no_database_is_conversations_unavailable() -> None:
    async def go() -> None:
        db = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.3)
        await db.open()
        try:
            conversations: Conversations = PostgresConversations(db, POLICY)
            with pytest.raises(ConversationsUnavailable):
                await conversations.spoken(1, "device:7", 1, 120)
        finally:
            await db.close()

    run(go())


def test_spoken_on_the_unwired_service_is_unavailable() -> None:
    async def go() -> None:
        with pytest.raises(ConversationsUnavailable):
            await Conversations.null().spoken(1, "device:7", 1, 120)

    run(go())
