"""Directed, not blind: a conversation records the channel and place it started on when it is created, and never
changes them afterwards, whatever later calls on its thread pass."""

import psycopg
from ashley.conversations.model import NewTurn
from conversations_support import household, person, run, service


def row(url: str, conversation_id: int) -> tuple[str | None, str | None]:
    with psycopg.connect(url) as conn:
        found = conn.execute("SELECT channel, place FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
    assert found is not None
    return found


def test_start_records_channel_and_place_and_defaults_to_unknown(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            heard = await conversations.start(home, "command", [], channel="voice", place="kitchen")
            typed = await conversations.start(home, "chat", [], channel="web")
            bare = await conversations.start(home, "chat", [])
        assert row(db_url, heard.id) == ("voice", "kitchen")
        assert row(db_url, typed.id) == ("web", None)
        assert row(db_url, bare.id) == (None, None)

    run(scenario())


def test_a_thread_records_them_when_it_starts_a_conversation_and_keeps_them_when_it_continues(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            first = await conversations.for_thread(home, "device:1", "chat", [alana], channel="device", place="hallway")
            await conversations.add_turn(first.id, NewTurn("person", "hello", alana))
            again = await conversations.for_thread(home, "device:1", "chat", [alana], channel="voice", place="kitchen")
            other = await conversations.for_thread(home, "discord:9", "chat", [alana], channel="discord")
        assert again.id == first.id
        assert row(db_url, first.id) == ("device", "hallway")
        assert row(db_url, other.id) == ("discord", None)

    run(scenario())
