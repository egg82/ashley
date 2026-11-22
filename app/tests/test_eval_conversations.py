"""A conversation an evaluation opens (`Inbound.eval`), over a real database: never remembered, and left out of the
person's list and of when they last spoke."""

from datetime import datetime

from ashley.conversations.model import NewTurn
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar, service
from test_wakes_postgres import device, store, wake


def test_a_person_lists_the_conversation_they_had_and_not_the_evaluation_that_ran_as_them(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            real = await conv.for_thread(home, "device:1", "chat", [mine])
            test = await conv.for_thread(home, "scored-1", "chat", [mine], eval=True)
            for made in (real, test):
                await conv.add_turn(made.id, NewTurn("person", "hello", mine))
            assert [s.id for s in (await conv.of_person(home, mine, 10)).items] == [real.id]
            assert [s.id for s in (await conv.of_person(home, mine, 10, thread="scored-1")).items] == []
            assert (await conv.get(test.id)) is not None

    run(scenario())


def test_an_evaluation_is_never_remembered_whatever_the_caller_asks(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.start(home, "chat", [mine], remembered=True, eval=True)
            threaded = await conv.for_thread(home, "scored-2", "chat", [mine], remembered=True, eval=True)
            plain = await conv.start(home, "chat", [mine], remembered=True)
        rows = {i: scalar(db_url, "SELECT remembered FROM conversations WHERE id = %s", (i,))
                for i in (started.id, threaded.id, plain.id)}
        assert rows == {started.id: False, threaded.id: False, plain.id: True}

    run(scenario())


def test_an_evaluation_turn_by_the_person_does_not_move_when_they_last_spoke(db_url: str) -> None:
    home = household(db_url)
    mine = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv, store(db_url) as wakes:
            made = (await wakes.receive(device(db_url, home), wake(home))).id
            assert (await wakes.said_before(made, mine)).heard_at is None
            test = await conv.for_thread(home, "scored-3", "chat", [mine], eval=True)
            await conv.add_turn(test.id, NewTurn("person", "hello", mine))
            assert (await wakes.said_before(made, mine)).heard_at is None
            real = await conv.for_thread(home, "device:2", "chat", [mine])
            await conv.add_turn(real.id, NewTurn("person", "hello", mine))
            heard = (await wakes.said_before(made, mine)).heard_at
            assert isinstance(heard, datetime)

    run(scenario())
