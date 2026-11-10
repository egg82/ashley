"""A person turn may carry an attachment (`NewTurn.attachment`): a block the person pasted, with an optional title, kept
with the turn and read back on every read of it, carried turns included. Only a person's turn takes one."""

import pytest
from ashley.conversations.model import Attachment, Author, Hearer, NewTurn
from conversations_support import household, person, run, scalar, service

PASTED = Attachment("Assignment brief", "Write 1,500 words on\nthe ecological model.\n" * 40)


def test_an_attachment_is_stored_with_its_turn_and_read_back_by_every_read(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            talk = await conv.start(home, "chat", [alana])
            stored = await conv.add_turn(talk.id, NewTurn("person", "here is the brief:", alana, "shared",
                                                          attachment=PASTED))
            plain = await conv.add_turn(talk.id, NewTurn("person", "and nothing else", alana, "shared"))
            assert stored.attachment == PASTED and plain.attachment is None
            read = await conv.get(talk.id)
            assert read is not None and [t.attachment for t in read.turns] == [PASTED, None]
            later = await conv.add_turn(talk.id, NewTurn("ashley", "ok", heard="shared"))
            got = await conv.carried(Hearer(home, alana, owner_only=False), talk.id, later.id, "ok", 5, 0)
            assert [t.attachment for t in got.recent] == [PASTED, None]

    run(scenario())


def test_an_attachment_without_a_title_keeps_its_text(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            talk = await conv.start(home, "chat", [alana])
            stored = await conv.add_turn(talk.id, NewTurn("person", "look", alana, "shared",
                                                          attachment=Attachment(None, "a log line")))
            assert stored.attachment == Attachment(None, "a log line")

    run(scenario())


@pytest.mark.parametrize("author", ["ashley", "household"])
def test_only_a_person_turn_takes_an_attachment(db_url: str, author: Author) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            talk = await conv.start(home, "chat", [alana])
            with pytest.raises(ValueError):
                await conv.add_turn(talk.id, NewTurn(author, "hi", heard="shared", attachment=PASTED))
        assert scalar(db_url, "SELECT count(*) FROM turns") == 0

    run(scenario())


def test_a_blank_attachment_is_refused(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conv:
            talk = await conv.start(home, "chat", [alana])
            with pytest.raises(ValueError):
                await conv.add_turn(talk.id, NewTurn("person", "hi", alana, "shared", attachment=Attachment("t", "  \n")))

    run(scenario())
