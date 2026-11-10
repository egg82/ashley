"""Remembered conversations: `devices.remembers` and `conversations.remembered` default true; a device made with
`--not-remembered` is not; a conversation records the value it is started with and keeps it when continued; and the
memory write job's candidates never include one that is not remembered."""

import re

import pytest
from ashley.channels.devices.__main__ import main, parser
from ashley.channels.model import Device
from ashley.conversations.model import Kind
from ashley.channels.postgres_devices import PostgresDevices
from ashley.db.pool import PoolDatabase
from ashley.memory.postgres import PostgresMemory

from conversations_support import POLICY, household, person, place_before_now, run, scalar, service
from memory_support import conversation, pool, say

IDLE: dict[Kind, float] = {kind: timing.idle_after_s for kind, timing in POLICY.timings.items()}
CHAT_IDLE = POLICY.timings["chat"].idle_after_s
CHAT_CLOSED = POLICY.timings["chat"].closed_after_s
ADD = ("--place", "hall", "--audience", "present", "--medium", "text", "--kind", "chat")


def remembered(url: str, conversation_id: int) -> object:
    return scalar(url, "SELECT remembered FROM conversations WHERE id = %s", (conversation_id,))


# --- devices -----------------------------------------------------------------------------------------------------


def added(url: str, *, remembers: bool | None) -> tuple[Device, str]:
    async def scenario() -> tuple[Device, str]:
        db = PoolDatabase(url)
        await db.open()
        try:
            devices = PostgresDevices(db)
            home = household(url)
            if remembers is None:
                _, token = await devices.add(home, "tab", "hall", "present", "text", "chat")
            else:
                _, token = await devices.add(home, "tab", "hall", "present", "text", "chat", remembers)
            found = await devices.by_token(token)
            assert found is not None
            return found, token
        finally:
            await db.close()

    out: list[tuple[Device, str]] = []

    async def hold() -> None:
        out.append(await scenario())

    run(hold())
    return out[0]


def test_a_device_is_remembered_unless_added_otherwise(db_url: str) -> None:
    found, _ = added(db_url, remembers=None)
    assert found.remembers is True
    assert scalar(db_url, "SELECT remembers FROM devices WHERE id = %s", (found.id,)) is True


def test_a_device_added_not_remembered_signs_in_as_such(db_url: str) -> None:
    found, _ = added(db_url, remembers=False)
    assert found.remembers is False
    assert scalar(db_url, "SELECT remembers FROM devices WHERE id = %s", (found.id,)) is False


def test_the_cli_flag_makes_a_device_not_remembered_and_its_absence_a_remembered_one() -> None:
    assert parser().parse_args(["add", "1", "tab", *ADD, "--not-remembered"]).not_remembered is True
    assert parser().parse_args(["add", "1", "tab", *ADD]).not_remembered is False


def test_the_cli_stores_the_device_it_was_told_to(db_url: str, monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    monkeypatch.setenv("DATABASE_URL", db_url)
    stored: dict[str, object] = {}
    for name, flags in (("plain", ()), ("test", ("--not-remembered",))):
        assert main(["add", str(home), name, *ADD, *flags]) == 0
        found = re.search(r"^device (\d+)$", capsys.readouterr().out, re.MULTILINE)
        assert found is not None
        device_id = int(found[1])
        stored[name] = scalar(db_url, "SELECT remembers FROM devices WHERE id = %s", (device_id,))
    assert stored == {"plain": True, "test": False}


# --- conversations -----------------------------------------------------------------------------------------------


def test_a_started_conversation_is_remembered_by_default_and_records_what_it_is_given(db_url: str) -> None:
    home = household(db_url)

    async def scenario() -> list[int]:
        async with service(db_url) as conv:
            return [(await conv.start(home, "chat", [])).id,
                    (await conv.start(home, "chat", [], remembered=False)).id,
                    (await conv.start(home, "chat", [], remembered=True)).id]

    out: list[list[int]] = []

    async def hold() -> None:
        out.append(await scenario())

    run(hold())
    assert [remembered(db_url, i) for i in out[0]] == [True, False, True]


@pytest.mark.parametrize("first", [True, False])
def test_a_continued_conversation_keeps_the_value_it_started_with(db_url: str, first: bool) -> None:
    home = household(db_url)
    who = person(db_url, home)
    ids: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            started = await conv.for_thread(home, "device:1", "chat", [who], remembered=first)
            again = await conv.for_thread(home, "device:1", "chat", [who], remembered=not first)
            ids.extend([started.id, again.id])

    run(scenario())
    assert ids[0] == ids[1]
    assert remembered(db_url, ids[0]) is first


def test_a_thread_whose_conversation_closed_starts_one_with_the_newly_passed_value(db_url: str) -> None:
    home = household(db_url)
    ids: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            first = await conv.for_thread(home, "device:1", "chat", [], remembered=False)
            place_before_now(db_url, first.id, CHAT_CLOSED + 1)
            second = await conv.for_thread(home, "device:1", "chat", [], remembered=True)
            ids.extend([first.id, second.id])

    run(scenario())
    assert ids[0] != ids[1]
    assert (remembered(db_url, ids[0]), remembered(db_url, ids[1])) == (False, True)


# --- the write job's candidates -----------------------------------------------------------------------------------


def test_a_conversation_that_is_not_remembered_is_never_a_candidate_for_a_write(db_url: str) -> None:
    home = household(db_url)
    kept, forgotten = conversation(db_url, home), conversation(db_url, home)
    for talk in (kept, forgotten):
        say(db_url, talk, "I like tea", "Noted")
        place_before_now(db_url, talk, CHAT_IDLE + 1)
    scalar(db_url, "UPDATE conversations SET remembered = false WHERE id = %s RETURNING id", (forgotten,))

    async def scenario() -> None:
        async with pool(db_url) as db:
            found = await PostgresMemory(db).unwritten(IDLE, 10, 3)
            assert [u.conversation_id for u in found] == [kept]

    run(scenario())


def test_a_conversation_started_not_remembered_is_not_a_candidate_even_when_closed(db_url: str) -> None:
    home = household(db_url)
    ids: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            ids.extend([(await conv.start(home, "chat", [], remembered=False)).id,
                        (await conv.start(home, "chat", [])).id])
        for talk in ids:
            say(db_url, talk, "I like tea")
            place_before_now(db_url, talk, CHAT_CLOSED + 1)
        async with pool(db_url) as db:
            found = await PostgresMemory(db).unwritten(IDLE, 10, 3)
            assert [u.conversation_id for u in found] == [ids[1]]

    run(scenario())
