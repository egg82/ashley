"""A reminder's turn looks before it reminds: it is offered only the tools that change nothing, and only where its reply
reaches the person alone (`Reading`, `Inbound.reads_only`); one a deposit fired states that deposit from fields."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.channels.wake.reminder_turn import inbound as reminder_inbound
from ashley.channels.wake.reminder_turn import said
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Person
from ashley.senses.deposit_rule import Landed, landed_from_json, landed_to_json
from ashley.senses.wakes import Reminder
from ashley.tools.reading import Reading
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import run

LOOK = ToolSpec("look", "reads", {"type": "object"}, reads=True)
ACT = ToolSpec("act", "changes", {"type": "object"})
SAM, ALANA = Person(2, 1, "Sam"), Person(3, 1, "Alana")
LANDED = Landed(250_000, date(2026, 11, 3), "Checking", "Acme Corp Bonus")


class Source(Tools):
    def __init__(self) -> None:
        self.ran: list[str] = []

    async def catalogue(self) -> Catalogue:
        return Catalogue((LOOK, ACT), "guidance")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call.name)
        return ToolResult(call.id, "ok")


def test_reading_lists_and_runs_only_what_reads() -> None:
    async def go() -> None:
        source = Source()
        reading = Reading(source)
        got = await reading.catalogue()
        assert [s.name for s in got.specs] == ["look"] and got.instructions == "guidance"
        assert not (await reading.call(ToolCall("1", "look", {}))).is_error
        assert (await reading.call(ToolCall("2", "act", {}))).is_error
        assert source.ran == ["look"]

    run(go())


def test_reading_runs_nothing_before_it_has_listed_what_reads() -> None:
    async def go() -> None:
        source = Source()
        assert (await Reading(source).call(ToolCall("1", "act", {}))).is_error and source.ran == []

    run(go())


def turn(**changes: Any) -> Inbound:
    base: dict[str, Any] = dict(household_id=10, thread="push:2", text="m", kind="chat", medium="text", audience="owner",
                                speaker_id=2, shared=False, place=None, channel="device", reads_only=True)
    return Inbound(**{**base, **changes})


@pytest.mark.parametrize(("changes", "offered"), [({}, ["look"]), ({"shared": True}, []), ({"audience": "household"}, []),
                                                  ({"device_id": 4}, []), ({"speaker_id": None}, [])])
def test_a_reads_only_turn_is_offered_reads_only_where_its_reply_reaches_the_person_alone(
        changes: dict[str, Any], offered: list[str]) -> None:
    services.register(Tools, Source())

    async def go() -> None:
        got = await for_turn(turn(**changes)).catalogue()
        assert [s.name for s in got.specs if s.name in ("look", "act")] == offered
        assert "act" not in [s.name for s in got.specs]

    run(go())


def test_a_turn_not_reads_only_is_offered_the_changes_too() -> None:
    services.register(Tools, Source())

    async def go() -> None:
        got = await for_turn(turn(reads_only=False)).catalogue()
        assert {"look", "act"} <= {s.name for s in got.specs}

    run(go())


def test_the_fired_turn_offers_reads_only_and_still_goes_out() -> None:
    got = reminder_inbound(7, Reminder(1, 2, 3, "move it", datetime.now(UTC), None), SAM, ALANA)
    assert got.reads_only and got.tools_only is None and got.promised


def test_a_deposit_reminder_states_the_deposit_from_its_fields() -> None:
    text = said(Reminder(1, 2, 3, "move it", datetime.now(UTC), None, LANDED), SAM, ALANA)
    assert "2500.00 on 2026-11-03 into Checking, from Acme Corp Bonus" in text
    assert "landed" not in said(Reminder(1, 2, 3, "move it", datetime.now(UTC), None), SAM, ALANA)
    bare = said(Reminder(1, 2, 3, "x", datetime.now(UTC), None, Landed(5, date(2026, 11, 3), "Checking", None)), SAM, ALANA)
    assert "0.05 on 2026-11-03 into Checking." in bare


def test_a_landed_deposit_round_trips_and_refuses_what_it_did_not_make() -> None:
    assert landed_from_json(landed_to_json(LANDED)) == LANDED
    for bad in ({}, {**landed_to_json(LANDED), "extra": 1}, {**landed_to_json(LANDED), "cents": "1"},
                {**landed_to_json(LANDED), "day": "soon"}):
        with pytest.raises(ValueError):
            landed_from_json(bad)
