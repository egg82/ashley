"""A person turn's `source` over a real database: one message handed in twice is one turn of the household, returned
whichever conversation the second hand-in names and even once that one has closed; another household's message with
the same source is its own; a turn of hers with a source is refused."""

import pytest
from ashley.conversations.model import NewTurn
from contract.conversations_support import household, person, run, scalar, service, shift_back
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


def said(text: str, who: int, source: str | None) -> NewTurn:
    return NewTurn("person", text, who, "private", who, source=source)


def test_a_message_handed_in_twice_is_one_turn_wherever_it_is_handed_in(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            first = await conversations.start(home, "command", [alana])
            stored = await conversations.add_turn(first.id, said("hello", alana, "discord:1"))
            shift_back(db_url, first.id, 1_000)
            other = await conversations.start(home, "command", [alana])
            again = await conversations.add_turn(other.id, said("hello", alana, "discord:1"))
            assert (again.id, again.text, again.conversation_id) == (stored.id, "hello", first.id)
            assert (await conversations.add_turn(other.id, said("hello", alana, "discord:2"))).id != stored.id
            assert (await conversations.add_turn(other.id, said("hello", alana, None))).id != stored.id

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 3


def test_another_households_message_with_the_same_source_is_its_own_turn(db_url: str) -> None:
    homes = [household(db_url, "one"), household(db_url, "two")]
    people = [person(db_url, h) for h in homes]

    async def scenario() -> None:
        async with service(db_url) as conversations:
            for home, who in zip(homes, people):
                started = await conversations.start(home, "chat", [who])
                await conversations.add_turn(started.id, said("hi", who, "discord:1"))

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 2


def test_a_turn_of_hers_with_a_source_is_refused(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [])
            with pytest.raises(ValueError):
                await conversations.add_turn(started.id, NewTurn("ashley", "hi", source="discord:1"))

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 0


def test_a_turn_of_the_household_has_a_source_but_no_speaker_no_held_line_and_answers_none(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            first = await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:1"))
            again = await conversations.add_turn(started.id, NewTurn("household", "event", source="wake:1"))
            assert (first.author, first.speaker_id) == ("household", None) and again.id == first.id
            for bad in (NewTurn("household", "event", speaker_id=alana), NewTurn("household", "event", follows=True),
                        NewTurn("household", "event", answers=first.id)):
                with pytest.raises(ValueError):
                    await conversations.add_turn(started.id, bad)

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 1
