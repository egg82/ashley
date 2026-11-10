"""Trigger A: a chat turn that reaches `max_tool_rounds` or `deadline_s` without its answer goes on, from its entries, on
the stronger route (task `escalated`) in place of the forced close on the fast one; with a held line to give, the loop
stops `Held` by `escalate` for trigger `a` first."""

from typing import Any

from ashley.channels.escalation import Escalation
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held
from ashley.inference.model import ToolCall, ToolCalls, ToolResults
from escalation_blind_support import (DONE, SWITCH, Clock, Lamp, Marks, Model, carried_on, done, drive, limits, rounds,
                                      stronger)


def answered(got: Answer | Held) -> Answer:
    assert isinstance(got, Answer)
    return got


def held(got: Answer | Held) -> Held:
    assert isinstance(got, Held)
    return got


def results_in(model: Model, step: int) -> int:
    return sum(isinstance(m, ToolResults) for m in model.seen[step].messages)


def run_drive(lim: Limits, escalation: Escalation | None, **kw: Any) -> tuple[Answer | Held, Marks]:
    return done(drive(lim, escalation, **kw))


def test_an_answer_before_the_round_limit_does_not_escalate(model: Model) -> None:
    model.script = [*rounds(1), DONE]
    got, marks = run_drive(limits(2), stronger())
    assert answered(got).reply == DONE
    assert model.tasks == ["chat", "chat"] and marks.marked == []


def test_a_turn_that_reaches_its_round_limit_asks_the_stronger_route_in_place_of_the_forced_close(model: Model) -> None:
    model.script = [*rounds(2), DONE]
    got, marks = run_drive(limits(2), stronger())
    assert answered(got).reply == DONE
    assert model.tasks == ["chat", "chat", "escalated"]
    assert model.choices("chat") == ["auto", "auto"]
    assert marks.marked == ["a"]


def test_without_an_escalation_the_same_turn_closes_on_the_fast_route_under_tool_choice_none(model: Model) -> None:
    """Control for the previous test: the close that escalation replaces."""
    model.script = [*rounds(2), DONE]
    got, marks = run_drive(limits(2), None)
    assert answered(got).reply == DONE
    assert model.tasks == ["chat"] * 3 and model.choices("chat") == ["auto", "auto", "none"]
    assert marks.marked == []


def test_the_stronger_route_sees_what_the_fast_one_found(model: Model) -> None:
    model.script = [*rounds(2), DONE]
    run_drive(limits(2), stronger())
    assert results_in(model, 2) == 2


def test_the_stronger_route_is_offered_the_tools_and_goes_on_under_auto(model: Model) -> None:
    model.script = [*rounds(2), DONE]
    run_drive(limits(2), stronger())
    assert model.seen[2].tools == (SWITCH.name,) and model.seen[2].tool_choice == "auto"


def test_the_stronger_route_is_not_asked_when_the_turn_ends_one_round_short_of_the_limit(model: Model) -> None:
    model.script = [*rounds(2), DONE]
    got, marks = run_drive(limits(3), stronger(5))
    assert answered(got).reply == DONE
    assert model.tasks == ["chat"] * 3 and marks.marked == []


def test_a_turn_with_a_line_to_give_stops_held_by_escalate_for_a_and_the_line_is_its_latest_aside(model: Model) -> None:
    model.script = [*rounds(2)]
    got, marks = run_drive(limits(2), stronger(), hold=True)
    stopped = held(got)
    assert (stopped.by, stopped.trigger) == ("escalate", "a")
    assert not stopped.reply.answers and stopped.reply.text == "Aside 2." and stopped.reply.spoken == "Aside 2."
    assert (stopped.rounds, stopped.calls) == (2, 2)
    assert model.tasks == ["chat", "chat"]
    assert marks.marked == ["a"]


def test_the_held_turn_goes_on_on_the_stronger_route_once_resumed(model: Model) -> None:
    model.script = [*rounds(2)]
    got, marks = run_drive(limits(2), stronger(), hold=True)
    model.script = [DONE]
    out = done(carried_on(held(got), limits(2), stronger(), marks=marks))
    assert out.reply == DONE
    assert model.tasks == ["chat", "chat", "escalated"] and results_in(model, 2) == 2
    assert marks.marked == ["a"]


def test_a_turn_at_its_limit_with_a_line_to_give_but_no_aside_closes_on_the_fast_route(model: Model) -> None:
    quiet = ToolCalls((ToolCall("c1", SWITCH.name, {"what": "lamp1"}), ))
    quiet2 = ToolCalls((ToolCall("c2", SWITCH.name, {"what": "lamp2"}), ))
    model.script = [quiet, quiet2, DONE]
    got, marks = run_drive(limits(2), stronger(), hold=True)
    assert answered(got).reply == DONE
    assert model.tasks == ["chat"] * 3 and model.choices("chat")[-1] == "none"
    assert marks.marked == []


def test_a_turn_past_its_deadline_asks_the_stronger_route(model: Model) -> None:
    clock = Clock()
    model.script = [*rounds(2), DONE]
    got, marks = run_drive(limits(10, deadline=40), stronger(20), lamp=Lamp(clock=clock, seconds=30), clock=clock)
    assert answered(got).reply == DONE
    assert model.tasks == ["chat", "chat", "escalated"]
    assert model.choices("chat") == ["auto", "auto"]
    assert marks.marked == ["a"]


def test_a_turn_inside_its_deadline_does_not_escalate(model: Model) -> None:
    clock = Clock()
    model.script = [*rounds(2), DONE]
    got, marks = run_drive(limits(10, deadline=40), stronger(20), lamp=Lamp(clock=clock, seconds=10), clock=clock)
    assert answered(got).reply == DONE
    assert model.tasks == ["chat"] * 3 and marks.marked == []


def test_a_turn_past_its_deadline_with_a_line_to_give_stops_held_by_escalate(model: Model) -> None:
    clock = Clock()
    model.script = [*rounds(2)]
    got, marks = run_drive(limits(10, deadline=40), stronger(20), hold=True, lamp=Lamp(clock=clock, seconds=30),
                           clock=clock)
    stopped = held(got)
    assert (stopped.by, stopped.trigger) == ("escalate", "a")
    assert model.tasks == ["chat", "chat"] and marks.marked == ["a"]


def test_a_held_turn_resumed_by_a_runner_that_kept_no_record_still_goes_on_the_stronger_route(model: Model) -> None:
    model.script = [*rounds(2)]
    got, _ = run_drive(limits(2), stronger(), hold=True)
    model.script = [DONE]
    out = done(carried_on(held(got), limits(2), stronger()))
    assert out.reply == DONE and model.tasks == ["chat", "chat", "escalated"]


def test_a_turn_past_its_deadline_before_any_call_has_nothing_to_go_on_with_and_does_not_escalate(model: Model) -> None:
    clock = Clock()
    model.script = [DONE]
    got, marks = run_drive(limits(10, deadline=40), stronger(20), clock=clock, started=clock.now - 100)
    assert answered(got).reply == DONE
    assert model.tasks == ["chat"] and marks.marked == []
