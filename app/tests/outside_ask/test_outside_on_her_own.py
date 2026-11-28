"""What she does on her own is recorded with its cause and undo: a change of a turn no person's message started is recorded
whether or not the turn read outside words, once, with the turn's cause; a person's own untainted turn records nothing;
a read, a failed call and a held one are never recorded; a person's own tainted turn is its own cause; the undo is the
one the tool's result carries; and the record line names ids and kinds, never a summary."""

import pytest
from ashley import logs, services
from ashley.inference.model import ToolResult
from ashley.senses.outside_record import Cause, OutsideRecord
from ashley.tools.outside import Standing
from ashley.undo import Undo
from outside_ask_support import CONVERSATION, HOUSEHOLD, SPEAKER, TURN, Fake, asked, build, run, spec
from outside_record_support import MemoryRecord

WAKE = Cause("wake", 31)
UNASKED = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=False, unasked=True, cause=WAKE)
ASKED = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=True)
UNDO = Undo("reminder_cancel", "88")
TOOLS = (spec("look", reads=True, outside=True), spec("peek", reads=True), spec("remind", tier="runs"),
         spec("lamp"), spec("wipe", tier="asks"))


def fake() -> Fake:
    return Fake(TOOLS, results={"remind": ToolResult("x", "set", undo=UNDO), "lamp": ToolResult("x", "on")})


def recorded() -> list[tuple[str, str, Cause | None, Undo | None]]:
    record = services.get(OutsideRecord)
    assert isinstance(record, MemoryRecord)
    return [(a.tool, a.tier, a.cause, a.undo) for a in record.actions]


def test_a_change_in_a_turn_nobody_asked_for_is_recorded_with_its_cause_and_undo() -> None:
    async def go() -> None:
        outside, ran, _ = build(fake(), UNASKED)
        await outside.catalogue()
        await outside.call(asked("remind", "a"))
        await outside.call(asked("lamp", "b"))
        assert [c.name for c in ran.ran] == ["remind", "lamp"]
        assert recorded() == [("remind", "runs", WAKE, UNDO), ("lamp", "runs", WAKE, None)]
        row = services.get(OutsideRecord)
        assert isinstance(row, MemoryRecord)
        assert {(a.household_id, a.person_id, a.conversation_id, a.turn_id) for a in row.actions} == {
            (HOUSEHOLD, SPEAKER, CONVERSATION, TURN)}

    run(go())


def test_a_persons_own_untainted_turn_records_nothing() -> None:
    async def go() -> None:
        outside, ran, _ = build(fake(), ASKED)
        await outside.catalogue()
        await outside.call(asked("remind", "a"))
        await outside.call(asked("lamp", "b"))
        assert [c.name for c in ran.ran] == ["remind", "lamp"], "the changes ran: control"
        assert recorded() == []

    run(go())


def test_a_read_a_failed_change_and_a_held_one_are_not_recorded_in_an_unasked_turn() -> None:
    async def go() -> None:
        failing = Fake(TOOLS, results={"lamp": ToolResult("x", "no such lamp", is_error=True)})
        outside, ran, _ = build(failing, UNASKED)
        await outside.catalogue()
        await outside.call(asked("peek", "a"))
        await outside.call(asked("lamp", "b"))
        await outside.call(asked("wipe", "c"))
        assert [c.name for c in ran.ran] == ["peek", "lamp"], "the held change never ran"
        assert recorded() == []

    run(go())


def test_an_unasked_turn_that_reads_outside_words_records_each_change_once_with_its_own_cause() -> None:
    async def go() -> None:
        outside, _, _ = build(fake(), UNASKED)
        await outside.catalogue()
        await outside.call(asked("remind", "a"))
        await outside.call(asked("look", "r"))
        assert outside.tainted == "look"
        await outside.call(asked("remind", "b"))
        assert recorded() == [("remind", "runs", WAKE, UNDO), ("remind", "runs", WAKE, UNDO)]

    run(go())


def test_a_persons_own_tainted_turn_is_its_own_cause() -> None:
    async def go() -> None:
        outside, _, _ = build(fake(), ASKED)
        await outside.catalogue()
        await outside.call(asked("look", "r"))
        await outside.call(asked("remind", "a"))
        assert recorded() == [("remind", "runs", Cause("turn", TURN), UNDO)]

    run(go())


def test_an_unasked_turn_whose_builder_named_no_cause_is_still_recorded_with_none() -> None:
    async def go() -> None:
        outside, _, _ = build(fake(), Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=False, unasked=True))
        await outside.catalogue()
        await outside.call(asked("lamp", "a"))
        assert recorded() == [("lamp", "runs", None, None)]

    run(go())


def test_the_record_line_carries_ids_and_kinds_never_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        outside, _, _ = build(fake(), UNASKED)
        await outside.catalogue()
        await outside.call(asked("remind", "a", what="Pay the Bluebird card"))

    run(go())
    line = next(x for x in capsys.readouterr().out.splitlines() if "event=outside.recorded" in x)
    assert "tool=remind" in line and "cause=wake" in line and "cause_id=31" in line and "undo=reminder_cancel" in line
    assert "Bluebird" not in line
