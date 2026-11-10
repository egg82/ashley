"""Conversations' log lines: the documented events with their ids, kinds and counts, and never a turn's text, a
person's name or a household's name, on success or on any refusal."""

import pytest
from ashley import logs
from ashley.conversations.conversations import (ConversationClosed, ConversationNotFound, UnknownHousehold,
                                                UnknownPerson)
from ashley.conversations.model import NewTurn
from conversations_support import POLICY, events, household, person, place_before_now, run, service

MARK = "zqPLANTED7731"


def values(line: dict[str, str]) -> set[str]:
    return set(line.values())


def test_start_logs_its_id_kind_and_participant_count(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    people = [person(db_url, home) for _ in range(3)]
    logs.setup()

    cids: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            for _ in range(4):   # an id past 3, so the id and the count cannot be mistaken for each other
                cids.append((await conv.start(home, "chat", [])).id)
            capsys.readouterr()
            cids.append((await conv.start(home, "brainstorm", people)).id)

    run(scenario())
    lines = events(capsys.readouterr().out, "conversation.started")
    assert len(lines) == 1
    assert {str(cids[-1]), "brainstorm", "3"} <= values(lines[0])


def test_a_stored_turn_logs_the_conversation_turn_and_author(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    mine = person(db_url, home)
    logs.setup()
    seen: list[tuple[int, int, str]] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "chat", [mine])).id
            for _ in range(3):   # ids past 1, so a conversation id and a turn id cannot be mistaken for each other
                await conv.add_turn(cid, NewTurn("ashley", "warming up"))
            capsys.readouterr()
            for turn in (NewTurn("person", "hello", mine), NewTurn("ashley", "hi")):
                stored = await conv.add_turn(cid, turn)
                seen.append((cid, stored.id, stored.author))

    run(scenario())
    lines = events(capsys.readouterr().out, "conversation.turn")
    assert len(lines) == 2
    for line, (cid, tid, author) in zip(lines, seen):
        assert {str(cid), str(tid), author} <= values(line)


def test_a_refused_turn_logs_turn_refused_and_no_turn(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url)
    logs.setup()
    cids: list[int] = []

    async def scenario() -> None:
        async with service(db_url) as conv:
            for _ in range(2):
                cids.append((await conv.start(home, "command", [])).id)
            place_before_now(db_url, cids[1], POLICY.timings["command"].closed_after_s + 1)
            capsys.readouterr()
            with pytest.raises(ConversationClosed):
                await conv.add_turn(cids[1], NewTurn("ashley", "too late"))

    run(scenario())
    out = capsys.readouterr().out
    refused = events(out, "conversation.turn_refused")
    assert len(refused) == 1
    assert str(cids[1]) in values(refused[0])
    assert len(refused[0]) > 5, "the line carries a reason beside ts, level, logger, event and the id"
    assert events(out, "conversation.turn") == []


def test_no_text_or_name_reaches_any_log_line(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    home = household(db_url, f"house {MARK}")
    elsewhere = household(db_url, f"other {MARK}")
    mine, theirs = person(db_url, home, f"Alana {MARK}"), person(db_url, elsewhere, f"Eve {MARK}")
    logs.setup()
    capsys.readouterr()

    async def scenario() -> None:
        async with service(db_url) as conv:
            cid = (await conv.start(home, "chat", [mine])).id
            closed = (await conv.start(home, "command", [mine])).id
            await conv.add_turn(cid, NewTurn("person", f"my secret is {MARK}", mine))
            await conv.add_turn(cid, NewTurn("ashley", f"{MARK}\nnoted"))
            await conv.add_turn(cid, NewTurn("person", f'"{MARK}" = said', None))
            place_before_now(db_url, closed, POLICY.timings["command"].closed_after_s + 1)
            refusals = [
                (ConversationClosed, conv.add_turn(closed, NewTurn("person", f"late {MARK}", mine))),
                (UnknownPerson, conv.add_turn(cid, NewTurn("person", f"intruder {MARK}", theirs))),
                (ConversationNotFound, conv.add_turn(987_654_321, NewTurn("person", f"nobody {MARK}"))),
                (UnknownPerson, conv.start(home, "chat", [theirs])),
                (UnknownHousehold, conv.start(987_654_321, "chat", [])),
                (ValueError, conv.add_turn(cid, NewTurn("ashley", f"{MARK}", mine))),
            ]
            for error, call in refusals:
                with pytest.raises(error):
                    await call
            await conv.get(cid)

    run(scenario())
    out = capsys.readouterr().out
    assert len(events(out, "conversation.turn")) == 3, "control: the turns were logged"
    assert len(events(out, "conversation.started")) == 2, "control: the starts were logged"
    assert len(events(out, "conversation.turn_refused")) >= 1, "control: the refusal was logged"
    assert MARK not in out
    for word in ("secret", "intruder", "noted", "Alana", "Eve"):
        assert word not in out
