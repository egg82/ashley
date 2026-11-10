"""Trigger B: the fast model's `Reply.escalate` is the line she says meanwhile; the turn goes on from its entries on the
stronger route (task `escalated`)."""

from typing import Any

import pytest
from ashley.channels.escalation import Escalation
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held
from ashley.inference.model import ToolResults, ToolSpec
from escalation_blind_support import (DONE, SWITCH, THINKING, Model, carried_on, done, drive, escalating, limits,
                                      rounds, stronger)

BOTH: list[tuple[ToolSpec, ...]] = [(SWITCH,), ()]


def run_drive(lim: Limits, escalation: Escalation | None, **kw: Any) -> Any:
    return done(drive(lim, escalation, **kw))


@pytest.mark.parametrize("tools", BOTH, ids=["with tools", "no tools"])
def test_a_reply_that_sets_escalate_goes_on_in_place_on_the_stronger_route(model: Model, tools: tuple[ToolSpec, ...]) -> None:
    model.script = [escalating(), DONE]
    got, marks = run_drive(limits(6), stronger(), tools=tools)
    assert isinstance(got, Answer) and got.reply == DONE
    assert model.tasks == ["chat", "escalated"]
    assert model.seen[1].tools == tuple(t.name for t in tools) and model.seen[1].tool_choice == "auto"
    assert marks.marked == ["b"]


@pytest.mark.parametrize("tools", BOTH, ids=["with tools", "no tools"])
def test_with_a_line_to_give_the_loop_stops_held_by_escalate_for_b_and_the_line_is_the_escalate_value(
        model: Model, tools: tuple[ToolSpec, ...]) -> None:
    model.script = [escalating()]
    got, marks = run_drive(limits(6), stronger(), hold=True, tools=tools)
    assert isinstance(got, Held)
    assert (got.by, got.trigger) == ("escalate", "b")
    assert not got.reply.answers and got.reply.text == THINKING and got.reply.spoken == THINKING
    assert model.tasks == ["chat"] and marks.marked == ["b"]


@pytest.mark.parametrize("tools", BOTH, ids=["with tools", "no tools"])
def test_the_held_turn_goes_on_on_the_stronger_route_once_resumed(model: Model, tools: tuple[ToolSpec, ...]) -> None:
    model.script = [escalating()]
    got, marks = run_drive(limits(6), stronger(), hold=True, tools=tools)
    assert isinstance(got, Held)
    model.script = [DONE]
    out = done(carried_on(got, limits(6), stronger(), marks=marks, tools=tools))
    assert out.reply == DONE
    assert model.tasks == ["chat", "escalated"] and model.seen[1].tool_choice == "auto"
    assert marks.marked == ["b"]


def test_the_stronger_route_sees_the_tool_results_the_fast_one_found(model: Model) -> None:
    model.script = [*rounds(1), escalating(), DONE]
    got, marks = run_drive(limits(6), stronger())
    assert isinstance(got, Answer) and got.reply == DONE
    assert model.tasks == ["chat", "chat", "escalated"]
    assert sum(isinstance(m, ToolResults) for m in model.seen[2].messages) == 1
    assert marks.marked == ["b"]


def test_a_turn_with_no_escalation_never_asks_the_stronger_route(model: Model) -> None:
    model.script = [escalating(), DONE, DONE]
    _, marks = run_drive(limits(6), None)
    assert "escalated" not in model.tasks and marks.marked == []


def test_a_turn_that_sets_nothing_escalates_nothing(model: Model) -> None:
    model.script = [DONE]
    got, marks = run_drive(limits(6), stronger(), hold=True)
    assert isinstance(got, Answer) and got.reply == DONE
    assert model.tasks == ["chat"] and marks.marked == []


@pytest.mark.parametrize("tools", BOTH, ids=["with tools", "no tools"])
def test_a_held_turn_resumed_by_a_runner_that_kept_no_record_still_goes_on_the_stronger_route(
        model: Model, tools: tuple[ToolSpec, ...]) -> None:
    """`Held.trigger` is the turn's own record of its escalation; the steps a resuming runner records in need not say."""
    model.script = [escalating()]
    got, _ = run_drive(limits(6), stronger(), hold=True, tools=tools)
    assert isinstance(got, Held)
    model.script = [DONE]
    out = done(carried_on(got, limits(6), stronger(), tools=tools))
    assert out.reply == DONE and model.tasks == ["chat", "escalated"]
