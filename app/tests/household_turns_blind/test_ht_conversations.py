"""A household turn over real Postgres: what the service refuses and how a source makes it once."""

import pytest
from ashley.conversations.model import NewTurn
from ashley.conversations.conversations import ConversationClosed
from contract.conversations_support import household, person, run, scalar, service, shift_back


def test_a_household_turn_refuses_a_speaker_a_follows_and_an_answers_and_writes_nothing(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            first = await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:1"))
            for bad in (NewTurn("household", "e", speaker_id=alana), NewTurn("household", "e", follows=True),
                        NewTurn("household", "e", answers=first.id), NewTurn("household", "  ")):
                with pytest.raises(ValueError):
                    await conversations.add_turn(started.id, bad)

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 1


def test_a_household_turn_is_stored_with_author_household_and_no_speaker(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            made = await conversations.add_turn(started.id, NewTurn("household", "alana_arrived · Alana"))
            assert (made.author, made.speaker_id, made.follows, made.answers) == ("household", None, False, None)
            got = await conversations.get(started.id)
            assert got is not None
            assert [(t.author, t.speaker_id, t.text) for t in got.turns] == [("household", None, "alana_arrived · Alana")]

    run(scenario())


def test_the_same_source_twice_is_one_turn_even_in_another_conversation(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            one = await conversations.start(home, "chat", [alana])
            two = await conversations.start(home, "chat", [alana])
            first = await conversations.add_turn(one.id, NewTurn("household", "event", source="wake:7"))
            again = await conversations.add_turn(two.id, NewTurn("household", "event", source="wake:7"))
            assert again.id == first.id and again.conversation_id == one.id
            other = await conversations.add_turn(one.id, NewTurn("household", "event", source="wake:8"))
            assert other.id != first.id
            none_a = await conversations.add_turn(one.id, NewTurn("household", "event"))
            none_b = await conversations.add_turn(one.id, NewTurn("household", "event"))
            assert none_a.id != none_b.id

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns WHERE source = 'wake:7'") == 1


def test_another_households_wake_with_the_same_source_is_its_own_turn(db_url: str) -> None:
    homes = [household(db_url, "one"), household(db_url, "two")]
    people = [person(db_url, h) for h in homes]

    async def scenario() -> None:
        async with service(db_url) as conversations:
            for home, who in zip(homes, people):
                started = await conversations.start(home, "chat", [who])
                await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:1"))

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns WHERE author = 'household'") == 2


def test_a_household_turn_does_not_make_anyone_a_participant(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:1"))
            got = await conversations.get(started.id)
            assert got is not None and got.participants == frozenset({alana})

    run(scenario())


def test_a_wake_handed_in_again_after_its_conversation_closed_returns_the_stored_turn(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            first = await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:5"))
            shift_back(db_url, started.id, 1_000_000)
            again = await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:5"))
            assert again.id == first.id
            with pytest.raises(ConversationClosed):
                await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:6"))

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 1
