"""A bench talk's ask carried from a chat turn (`carried_from`) is stored once however often it is added, and a turn of
hers that continues on a bench (`continued_on`) reads back; each is refused on the other author."""

import pytest
from ashley.conversations.model import NewTurn
from conversations_support import db_url as db_url, household, migrated_template as migrated_template, person, run, service


def test_a_carried_ask_is_stored_once_and_a_continuation_reads_back(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            chat = await conv.start(home, "chat", [alana])
            talk = await conv.start(home, "brainstorm", [alana])
            said = await conv.add_turn(chat.id, NewTurn("person", "work on it", alana))
            first = await conv.add_turn(talk.id, NewTurn("person", "work on it", alana, carried_from=said.id))
            again = await conv.add_turn(talk.id, NewTurn("person", "work on it", alana, carried_from=said.id))
            assert first.id == again.id and first.carried_from == said.id
            hers = await conv.add_turn(chat.id, NewTurn("ashley", 'Continued on bench "B".', answers=said.id,
                                                        continued_on=9))
            got = await conv.get(chat.id)
            assert got is not None and got.turns[-1] == hers and hers.continued_on == 9
            held = await conv.get(talk.id)
            assert held is not None and len(held.turns) == 1

    run(scenario())


def test_each_field_is_refused_on_the_other_author(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            chat = await conv.start(home, "chat", [alana])
            said = await conv.add_turn(chat.id, NewTurn("person", "hi", alana))
            for bad in (NewTurn("person", "x", alana, continued_on=3), NewTurn("ashley", "x", carried_from=said.id)):
                with pytest.raises(ValueError):
                    await conv.add_turn(chat.id, bad)

    run(scenario())
