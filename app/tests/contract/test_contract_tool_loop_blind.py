"""Blind contract tests of `ashley.channels.tool_loop`, part 1: the offer (K1) and the repeat rule (K4-K6).
Contract ids are in notes `blind-tool-loop.txt`; each test names the one it checks."""

from ashley.inference.model import ToolResult
from tool_loop_blind_support import (ANSWER, CHANGE, READ, READ2, SPECS, Rig, call, calls, rig as rig)


def test_k1_every_tool_is_offered_on_every_step_from_the_first(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a")), ANSWER)
    assert all(p.tools == SPECS for p in rig.inference.prompts) and len(rig.inference.prompts) == 2


# ---- repeat (K4-K6)

def test_k4_an_identical_read_in_a_later_round_is_not_run_again(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", q="x")), calls(call(READ.name, "id-b", q="x")), ANSWER)
    assert rig.source.ids() == ["id-a"]
    (second,) = rig.results_after(1)
    assert second.call_id == "id-b" and "id-a" in second.content


def test_k4_the_repeat_result_names_the_earlier_call_id(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "first-9f3", q="x")), calls(call(READ.name, "second", q="x")), ANSWER)
    assert "first-9f3" in rig.results_after(1)[-1].content


def test_k4_an_identical_read_twice_in_one_round_runs_once(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", q=1), call(READ.name, "id-b", q=1)), ANSWER)
    assert rig.source.ids() == ["id-a"]
    assert "id-a" in rig.results_after(0)[1].content


def test_k4_it_is_logged_tools_repeat(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", q=1)), calls(call(READ.name, "id-b", q=1)), ANSWER)
    assert len(rig.events("tools.repeat")) == 1


def test_k4_no_repeat_line_when_nothing_repeats(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", q=1)), calls(call(READ.name, "id-b", q=2)), ANSWER)
    assert rig.events("tools.repeat") == [] and rig.source.ids() == ["id-a", "id-b"]


def test_k4_different_arguments_or_a_different_name_run(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", q=1), call(READ.name, "id-b", q=2), call(READ2.name, "id-c", q=1),
                     call(READ.name, "id-d")), ANSWER)
    assert rig.source.ids() == ["id-a", "id-b", "id-c", "id-d"]


def test_k4_a_value_of_another_type_is_another_call(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", q=1), call(READ.name, "id-b", q="1"), call(READ.name, "id-c", q=True)), ANSWER)
    assert rig.source.ids() == ["id-a", "id-b", "id-c"]


def test_k4_key_order_is_ignored(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", x=1, y=2)), calls(call(READ.name, "id-b", y=2, x=1)), ANSWER)
    assert rig.source.ids() == ["id-a"]


def test_k4_key_order_is_ignored_inside_nested_arguments(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a", where={"city": "x", "zip": "1"})),
               calls(call(READ.name, "id-b", where={"zip": "1", "city": "x"})), ANSWER)
    assert rig.source.ids() == ["id-a"]


def test_k4_an_earlier_error_result_is_also_not_asked_again(rig: Rig) -> None:
    rig.source.results[READ.name] = ToolResult("", "boom", is_error=True)
    rig.answer(calls(call(READ.name, "id-a")), calls(call(READ.name, "id-b")), ANSWER)
    assert rig.source.ids() == ["id-a"]
    assert "id-a" in rig.results_after(1)[-1].content


def test_k4_the_earliest_call_is_the_one_named_after_three(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-a")), calls(call(READ.name, "id-b")), calls(call(READ.name, "id-c")), ANSWER)
    assert rig.source.ids() == ["id-a"]
    assert "id-a" in rig.results_after(2)[-1].content


def test_k5_a_change_that_ran_lets_the_same_read_run_again(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "r1")), calls(call(CHANGE.name, "id-c")), calls(call(READ.name, "r2")), ANSWER)
    assert rig.source.ids() == ["r1", "id-c", "r2"]


def test_k5_a_change_is_never_deduped(rig: Rig) -> None:
    rig.answer(calls(call(CHANGE.name, "c1", on=True), call(CHANGE.name, "c2", on=True)),
               calls(call(CHANGE.name, "c3", on=True)), ANSWER)
    assert rig.source.ids() == ["c1", "c2", "c3"]


def test_k5_the_same_arguments_to_a_change_and_a_read_are_not_confused(rig: Rig) -> None:
    rig.answer(calls(call(CHANGE.name, "id-c", q=1)), calls(call(READ.name, "r", q=1)), ANSWER)
    assert rig.source.ids() == ["id-c", "r"]


def test_k5_in_one_round_a_read_after_a_change_that_ran_runs_again(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "id-r1", q=1), call(CHANGE.name, "id-c"), call(READ.name, "id-r2", q=1)), ANSWER)
    assert rig.source.ids() == ["id-r1", "id-c", "id-r2"]
