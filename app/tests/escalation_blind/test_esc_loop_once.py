"""A turn escalates once, never a chain: on the stronger route a reply that sets `escalate`, or a limit, is not a trigger,
and the turn ends there as any other does, with a wrap-up at the stronger route's own limits."""

from typing import Any

from ashley.channels.escalation import Escalation
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Held
from ashley.inference.reply import Reply
from escalation_blind_support import (DONE, Clock, Lamp, Model, carried_on, done, drive, escalating, limits, rounds,
                                      stronger)


def run_drive(lim: Limits, escalation: Escalation | None, **kw: Any) -> Any:
    return done(drive(lim, escalation, **kw))


def test_a_stronger_route_reply_that_sets_escalate_is_answer_enough(model: Model) -> None:
    again = Reply(spoken=DONE.spoken, text=DONE.text, escalate="and again")
    model.script = [escalating(), again, DONE]
    got, marks = run_drive(limits(6), stronger())
    assert isinstance(got, Answer) and got.reply.text == DONE.text
    assert model.tasks == ["chat", "escalated"]
    assert marks.marked == ["b"]


def test_a_stronger_route_reply_that_sets_escalate_after_a_held_line_does_not_hold_again(model: Model) -> None:
    again = Reply(spoken=DONE.spoken, text=DONE.text, escalate="and again")
    model.script = [escalating()]
    got, marks = run_drive(limits(6), stronger(), hold=True)
    assert isinstance(got, Held)
    model.script = [again, DONE]
    out = done(carried_on(got, limits(6), stronger(), marks=marks))
    assert out.reply.text == DONE.text and model.tasks == ["chat", "escalated"]
    assert marks.marked == ["b"]


def test_the_stronger_route_reaching_its_own_round_limit_wraps_up_on_itself_not_a_second_escalation(
        model: Model) -> None:
    """The fast route stops at 2 rounds; the stronger one's limit of 4 counts on from there, so it gets 2 more."""
    model.script = [*rounds(4), DONE]
    got, marks = run_drive(limits(2), stronger(4))
    assert isinstance(got, Answer) and got.reply == DONE
    assert model.tasks == ["chat", "chat", "escalated", "escalated", "escalated"]
    assert model.choices("escalated") == ["auto", "auto", "none"]
    assert marks.marked == ["a"]


def test_the_held_turn_that_hits_the_stronger_routes_limit_wraps_up_on_it_and_returns_an_answer(model: Model) -> None:
    model.script = [*rounds(2)]
    got, marks = run_drive(limits(2), stronger(4), hold=True)
    assert isinstance(got, Held)
    model.script = [*rounds(2, start=3), DONE]
    out = done(carried_on(got, limits(2), stronger(4), marks=marks))
    assert isinstance(out, Answer) and out.reply == DONE
    assert model.choices("escalated") == ["auto", "auto", "none"] and model.tasks.count("chat") == 2
    assert marks.marked == ["a"]


def test_the_stronger_route_past_its_own_deadline_wraps_up_on_itself(model: Model) -> None:
    clock = Clock()
    model.script = [*rounds(2), DONE]
    got, marks = run_drive(limits(10, deadline=40), stronger(20, deadline=50),
                           lamp=Lamp(clock=clock, takes=[45, 60]), clock=clock)
    assert isinstance(got, Answer) and got.reply == DONE
    assert model.tasks == ["chat", "escalated", "escalated"]
    assert model.choices("escalated") == ["auto", "none"]
    assert marks.marked == ["a"]


def test_a_turn_already_escalated_by_an_earlier_runner_goes_on_on_the_stronger_route_without_marking_again(
        model: Model) -> None:
    """The checkpoint says it escalated (`Steps.escalated`): the loop starts on the stronger route."""
    from escalation_blind_support import Marks
    model.script = [DONE]
    got, marks = run_drive(limits(2), stronger(), marks=Marks("b"))
    assert isinstance(got, Answer) and got.reply == DONE
    assert model.tasks == ["escalated"] and marks.marked == []
