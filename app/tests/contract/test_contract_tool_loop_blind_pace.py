"""Blind contract tests of `ashley.channels.tool_loop`, part 2: pace (K7-K11): the aside field, the aside-budget hold,
the deadline, and `resume`. Contract ids are in notes `blind-tool-loop.txt`."""

import json

import pytest
from ashley.channels import aside
from ashley.channels.tool_loop import Answer
from ashley.inference.model import ToolCalls, ToolSpec
from tool_loop_blind_support import (ANSWER, CHANGE, CID, LOOK, READ, READ2, SPECS, Rig, as_answer,
                                     as_held, call, calls, limits, rig as rig)


def ask(id_: str, name: str = READ.name, line: str | None = "checking", **arguments: object) -> ToolCalls:
    extra = {} if line is None else {aside.FIELD: line}
    return calls(call(name, id_, **arguments, **extra))


# ---- the aside field (K7)

def test_k7_every_tool_is_offered_with_a_required_string_aside_on_a_holdable_turn(rig: Rig) -> None:
    rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5))
    offered = rig.inference.prompts[0].tools
    assert [t.name for t in offered] == [t.name for t in SPECS]
    for tool in offered:
        schema = json.loads(json.dumps(dict(tool.parameters)))
        assert aside.FIELD in schema["properties"] and aside.FIELD in schema["required"]
        assert schema["properties"][aside.FIELD]["type"] == "string"
    assert [t.reads for t in offered] == [t.reads for t in SPECS]


def test_k7_without_hold_the_tools_are_offered_as_they_are(rig: Rig) -> None:
    rig.answer(ask("a"), ANSWER, hold=False, lim=limits(hold=5))
    assert rig.inference.prompts[0].tools == SPECS


def test_k7_with_no_tools_nothing_is_offered_and_nothing_holds(rig: Rig) -> None:
    out = rig.answer(ANSWER, hold=True, tools=(), lim=limits(hold=0.5))
    assert as_answer(out).reply == ANSWER and rig.inference.prompts[0].tools == ()


def test_k7_the_source_never_sees_the_aside(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "r", q=1, aside="looking"), call(READ2.name, "w", aside="and this")),
               calls(call(CHANGE.name, "c", on=True, aside="doing it")), ANSWER, hold=True)
    assert [dict(c.arguments) for c in rig.source.called] == [{"q": 1}, {}, {"on": True}]


def test_k7_a_tool_whose_own_parameters_name_an_aside_keeps_it(rig: Rig) -> None:
    own = ToolSpec("note", "n", {"type": "object", "properties": {"aside": {"type": "string"}}}, reads=True)
    rig.answer(calls(call("note", "n1", aside="mine")), ANSWER, hold=True, tools=(own,))
    assert [dict(c.arguments) for c in rig.source.called] == [{"aside": "mine"}]


def test_k7_without_hold_the_source_gets_the_arguments_as_sent(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "r", q=1)), ANSWER, hold=False)
    assert [dict(c.arguments) for c in rig.source.called] == [{"q": 1}]


# ---- the aside-budget hold (K8, K9)

def test_k8_past_hold_after_the_latest_aside_is_returned_as_held(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(ask("a", line="Checking the lights."), ANSWER, hold=True, lim=limits(hold=5)))
    assert held.by == "aside_budget"
    assert held.reply.spoken == held.reply.text == "Checking the lights."
    assert held.rounds == 1 and held.calls == 1 and len(rig.inference.prompts) == 1


def test_k8_the_held_entries_end_with_the_results_so_far(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5)))
    assert [type(e).__name__ for e in held.entries][-2:] == ["ToolCalls", "ToolResults"]
    assert rig.source.ids() == ["a"]


def test_k8_before_hold_after_nothing_holds(rig: Rig) -> None:
    rig.inference.seconds = [4.0]
    out = rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5))
    assert isinstance(out, Answer) and len(rig.inference.prompts) == 2


def test_k8_without_hold_nothing_holds_by_time(rig: Rig) -> None:
    rig.inference.seconds = [60.0]
    assert isinstance(rig.answer(ask("a"), ANSWER, hold=False, lim=limits(hold=5)), Answer)


def test_k8_no_aside_no_hold_by_time(rig: Rig) -> None:
    rig.inference.seconds = [60.0]
    out = rig.answer(ask("a", line=None), ANSWER, hold=True, lim=limits(hold=5))
    assert isinstance(out, Answer)


@pytest.mark.parametrize("blank", ["", "   "])
def test_k8_a_blank_aside_is_no_aside(rig: Rig, blank: str) -> None:
    rig.inference.seconds = [60.0]
    assert isinstance(rig.answer(ask("a", line=blank), ANSWER, hold=True, lim=limits(hold=5)), Answer)


def test_k8_the_line_is_the_latest_aside_of_the_turn(rig: Rig) -> None:
    rig.inference.seconds = [2.0, 4.0]
    held = as_held(rig.answer(ask("a", line="first"), ask("b", line="second", q=2), ANSWER, hold=True,
                              lim=limits(hold=5)))
    assert held.reply.spoken == "second" and held.rounds == 2


def test_k8_a_later_call_without_an_aside_leaves_the_latest_one_that_had_one(rig: Rig) -> None:
    rig.inference.seconds = [2.0, 4.0]
    held = as_held(rig.answer(ask("a", line="first"), ask("b", line=None, q=2), ANSWER, hold=True,
                              lim=limits(hold=5)))
    assert held.reply.spoken == "first"


def test_k8_in_one_round_the_first_call_with_an_aside_gives_the_line(rig: Rig) -> None:
    rig.inference.seconds = [9.0]
    both = calls(call(READ.name, "a", aside="one"), call(READ2.name, "b", aside="two"))
    assert as_held(rig.answer(both, ANSWER, hold=True, lim=limits(hold=5))).reply.spoken == "one"


def test_k8_the_first_step_is_never_held_by_time(rig: Rig) -> None:
    rig.clock.advance(100)
    out = rig.answer(ANSWER, hold=True, lim=limits(hold=5), started=1000.0)
    assert as_answer(out).reply == ANSWER


def test_k8_k9_the_turn_holds_at_most_once_and_resume_goes_on_under_auto(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5)))
    out = rig.resume(held, ask("b", line="again", q=2), ask("c", line="and again", q=3), ANSWER, lim=limits(hold=5))
    assert out.reply == ANSWER and out.rounds == 3 and out.calls == 3
    assert rig.inference.choices == ["auto", "auto", "auto", "auto"]


def test_k8_the_resumed_turn_is_offered_the_tools_with_asides_still(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5)))
    rig.resume(held, ANSWER, lim=limits(hold=5))
    assert rig.inference.prompts[-1].tools == rig.inference.prompts[0].tools


def test_k9_a_reply_that_is_not_the_answer_is_held_by_not_answer(rig: Rig) -> None:
    held = as_held(rig.answer(LOOK, ANSWER, hold=True, lim=limits(hold=5)))
    assert held.by == "not_answer" and held.reply == LOOK


def test_k9_resume_of_not_answer_asks_under_auto(rig: Rig) -> None:
    held = as_held(rig.answer(LOOK, hold=True))
    out = rig.resume(held, ANSWER)
    assert out.reply == ANSWER and rig.inference.choices == ["auto", "auto"]


def test_k9_without_hold_a_reply_that_is_not_the_answer_is_dropped_and_asked_again_under_auto(rig: Rig) -> None:
    out = as_answer(rig.answer(LOOK, ANSWER, hold=False))
    assert out.reply == ANSWER and out.required == 1 and rig.inference.choices == ["auto", "auto"]


def test_k9_a_turn_held_by_not_answer_is_not_held_again_by_time(rig: Rig) -> None:
    held = as_held(rig.answer(LOOK, hold=True, lim=limits(hold=5)))
    rig.inference.seconds = [60.0]
    out = rig.resume(held, ask("a"), ANSWER, lim=limits(hold=5))
    assert out.reply == ANSWER


def test_k8_a_resumed_turn_held_by_time_is_not_held_by_not_answer_either(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5)))
    out = rig.resume(held, LOOK, ANSWER, lim=limits(hold=5))
    assert isinstance(out, Answer) and out.reply == ANSWER and out.required == 1
    assert rig.inference.choices[-2:] == ["auto", "auto"]


# ---- the deadline (K10, K11)

def test_k10_past_the_deadline_the_next_step_is_under_tool_choice_none(rig: Rig) -> None:
    rig.inference.seconds = [11.0]
    out = as_answer(rig.answer(ask("a", line=None), calls(call(READ2.name, "b")), ANSWER, lim=limits(deadline=10)))
    assert rig.inference.choices == ["auto", "none"] and out.reply == ANSWER and out.rounds == 1
    assert rig.source.ids() == ["a"]


def test_k10_before_the_deadline_every_step_is_auto(rig: Rig) -> None:
    rig.inference.seconds = [9.0]
    rig.answer(ask("a", line=None), ANSWER, lim=limits(deadline=10))
    assert rig.inference.choices == ["auto", "auto"]


def test_k10_it_is_logged_with_the_conversation_rounds_and_duration(rig: Rig) -> None:
    rig.inference.seconds = [11.0]
    rig.answer(ask("a", line=None), ANSWER, lim=limits(deadline=10))
    (line,) = rig.events("respond.deadline")
    assert str(CID) in line.values() and "1" in line.values() and "11000" in line.values()


def test_k10_no_deadline_line_when_the_deadline_never_passes(rig: Rig) -> None:
    rig.answer(ask("a", line=None), ANSWER, lim=limits(deadline=10))
    assert rig.events("respond.deadline") == []


def test_k10_the_deadline_counts_from_started_not_from_the_call(rig: Rig) -> None:
    rig.clock.advance(50)
    rig.answer(ANSWER, lim=limits(deadline=10), started=1000.0)
    assert rig.inference.choices == ["none"]
    (line,) = rig.events("respond.deadline")
    assert "0" in line.values() and "50000" in line.values()


def test_k10_the_deadline_applies_without_hold(rig: Rig) -> None:
    rig.inference.seconds = [30.0]
    rig.answer(calls(call(READ.name, "a")), ANSWER, hold=False, lim=limits(deadline=10))
    assert rig.inference.choices == ["auto", "none"]


def test_k10_a_resumed_turn_counts_from_started(rig: Rig) -> None:
    rig.inference.seconds = [6.0, 0.0]
    held = as_held(rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5, deadline=10)))
    rig.clock.advance(5.0)
    rig.resume(held, ANSWER, lim=limits(hold=5, deadline=10), started=1000.0)
    assert rig.inference.choices == ["auto", "none"]
    assert len(rig.events("respond.deadline")) == 1


def test_k10_a_resume_without_started_counts_from_its_own_call(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(ask("a"), ANSWER, hold=True, lim=limits(hold=5, deadline=10)))
    rig.clock.advance(100.0)
    rig.resume(held, ANSWER, lim=limits(hold=5, deadline=10))
    assert rig.inference.choices == ["auto", "auto"]


def test_k11_with_no_hold_or_deadline_configured_neither_passes(rig: Rig) -> None:
    rig.inference.seconds = [1e9, 1e9]
    out = as_answer(rig.answer(ask("a"), ask("b", q=2), ANSWER, hold=True, lim=limits()))
    assert out.reply == ANSWER and rig.inference.choices == ["auto", "auto", "auto"]


def test_k10_the_round_limit_still_ends_in_one_closing_step_under_none(rig: Rig) -> None:
    out = as_answer(rig.answer(ask("a", line=None), ask("b", q=2, line=None), ask("c", q=3, line=None),
                               lim=limits(rounds=2)))
    assert out.rounds == 2 and rig.inference.choices == ["auto", "auto", "none"]
