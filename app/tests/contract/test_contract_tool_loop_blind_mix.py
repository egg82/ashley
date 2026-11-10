"""Blind contract tests of `ashley.channels.tool_loop`, part 3: where the repeat rule and the pace meet. Contract ids and gaps (G3, G4) are in notes `blind-tool-loop.txt`."""

from ashley.channels import aside
from ashley.channels.tool_loop import Answer
from tool_loop_blind_support import (ANSWER, CHANGE, CHANGE2, READ, READ2, Rig, as_answer, as_held, call,
                                     calls, limits, rig as rig)

A = aside.FIELD


def test_x3_read_change_read_across_a_hold_and_resume_runs_the_second_read(rig: Rig) -> None:
    rig.inference.seconds = [0.0, 6.0]
    held = as_held(rig.answer(calls(call(READ.name, "r1", aside="a1")), calls(call(CHANGE.name, "c", aside="a3")),
                              ANSWER, hold=True, lim=limits(hold=5)))
    rig.resume(held, calls(call(READ.name, "r2", aside="a4")), ANSWER, lim=limits(hold=5))
    assert rig.source.ids() == ["r1", "c", "r2"]


def test_x4_a_read_before_the_hold_is_still_remembered_after_the_resume(rig: Rig) -> None:
    rig.inference.seconds = [6.0]
    held = as_held(rig.answer(calls(call(READ.name, "r1", q=1, aside="a1")), ANSWER, hold=True, lim=limits(hold=5)))
    rig.resume(held, calls(call(READ.name, "r2", q=1, aside="a2")), ANSWER, lim=limits(hold=5))
    assert rig.source.ids() == ["r1"]
    assert "r1" in rig.results_after(1)[-1].content
    assert len(rig.events("tools.repeat")) == 1


def test_x6_two_reads_differing_only_in_aside_run_once(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "r1", q=1, aside="one")), calls(call(READ.name, "r2", q=1, aside="two")),
               ANSWER, hold=True)
    assert rig.source.ids() == ["r1"]
    assert "r1" in rig.results_after(1)[-1].content


def test_x6b_a_read_with_an_aside_and_the_same_read_without_one_run_once(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "r1", q=1, aside="one")), calls(call(READ.name, "r2", q=1)), ANSWER, hold=True)
    assert rig.source.ids() == ["r1"]


def test_x7_a_repeated_read_that_carried_the_latest_aside_still_gives_the_hold_line(rig: Rig) -> None:
    rig.inference.seconds = [2.0, 6.0]
    held = as_held(rig.answer(calls(call(READ.name, "r1", q=1, aside="first")),
                              calls(call(READ.name, "r2", q=1, aside="second")), ANSWER, hold=True,
                              lim=limits(hold=5)))
    assert held.reply.spoken == "second" and rig.source.ids() == ["r1"]


def test_x13_a_hold_and_a_deadline_in_one_turn_hold_first_then_close(rig: Rig) -> None:
    rig.inference.seconds = [6.0, 5.0]
    lim = limits(hold=5, deadline=10)
    held = as_held(rig.answer(calls(call(READ.name, "r1", aside="a1")), ANSWER, hold=True, lim=lim))
    out = rig.resume(held, calls(call(READ2.name, "r2", aside="a2")), calls(call(READ.name, "r3", q=3)), ANSWER,
                     lim=lim, started=1000.0)
    assert isinstance(out, Answer) and rig.inference.choices == ["auto", "auto", "none"]
    assert rig.source.ids() == ["r1", "r2"]


def test_x14_counts_after_a_mixed_turn(rig: Rig) -> None:
    out = as_answer(rig.answer(calls(call(READ.name, "r1"), call(READ.name, "r2")),
                               calls(call(CHANGE.name, "c"), call(CHANGE2.name, "c2")), ANSWER))
    assert out.rounds == 2 and out.reply == ANSWER
    assert rig.source.ids() == ["r1", "c", "c2"]


def test_x16_in_one_round_a_read_after_a_change_that_ran_runs_again(rig: Rig) -> None:
    rig.answer(calls(call(READ.name, "r1", q=1), call(CHANGE.name, "c"), call(READ.name, "r2", q=1)), ANSWER)
    assert rig.source.ids() == ["r1", "c", "r2"]
