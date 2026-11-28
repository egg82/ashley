"""What her turn brought up (`NewTurn.shown`) over a real database: kept with her turn and read back equal and in order,
refused on a turn that is not hers (by the code and by the database itself), and none on a turn stored without any."""

import pytest
from ashley.conversations.model import Author, NewTurn, Shown
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar, service

SHOWN = (Shown("printer", "02X"), Shown("printer", "01P"))
NOT_HERS: tuple[Author, ...] = ("person", "household")


def test_her_turn_reads_back_with_what_it_brought_up_in_order(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [who])
            said = await conversations.add_turn(started.id, NewTurn("person", "show me the printers", who))
            kept = await conversations.add_turn(started.id, NewTurn("ashley", "Here.", answers=said.id, shown=SHOWN))
            plain = await conversations.add_turn(started.id, NewTurn("ashley", "Done.", answers=said.id))
            assert kept.shown == SHOWN and plain.shown == ()
            found = await conversations.get(started.id)
            assert found is not None
            read = {t.id: t.shown for t in found.turns}
            assert read == {said.id: (), kept.id: SHOWN, plain.id: ()}

    run(scenario())


def test_a_turn_that_is_not_hers_cannot_bring_anything_up(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [who])
            for author in NOT_HERS:
                with pytest.raises(ValueError):
                    await conversations.add_turn(started.id, NewTurn(author, "hi", shown=SHOWN))

    run(scenario())
    assert scalar(db_url, "SELECT count(*) FROM turns") == 0


def test_the_database_itself_refuses_a_brought_up_thing_on_a_turn_that_is_not_hers(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            await conversations.start(home, "chat", [who])

    run(scenario())
    with pytest.raises(Exception, match="turns_shown_hers"):
        scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text, shown) "
                       "SELECT id, household_id, 'person', 'x', '[{\"kind\": \"printer\", \"ref\": \"1\"}]'::jsonb "
                       "FROM conversations RETURNING id")
