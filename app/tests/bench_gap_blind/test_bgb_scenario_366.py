"""Outcome measures M1-M6 (spec, OUTCOME MEASURES) computed on a scripted replay shaped like one long bench conversation: ten
person turns on a 3d bench, with the shapes that went wrong there (a multi-call round past the old hold, a build
still calling tools at its deadline, a resumed turn that had waited, a promise at the close). The data is invented;
the measures come from the loop's fields, counts and fake seconds, never from her words. Targets are beating the
baseline the spec records (median M1 47 s, 3 of 10 over 5 minutes; 9 held lines; 4 of 10 empty answers; 3 open
closes; 2 deadline closes from the resume clock)."""

from dataclasses import dataclass, replace
from statistics import median

import pytest
from ashley.channels.checkpoint import dumps, loads
from ashley.channels.inflight import Saved
from ashley.channels.tool_loop import Answer, Progress, resumed
from ashley.conversations.inflight import Claim
from ashley.inference.model import ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from bgb_support import (CONVERSATION, EDIT, FINAL, HISTORY, LAST, PROMISE, READ, RUN, STOOD, SYSTEM, TOOLS, Rig,
                         Timed, brainstorm, drive, one, round_of)
from contract.inference_support import settle
from inflight_blind.ifb_checkpoint_support import checkpoint
from later_support import Logged

ANSWER = Reply(spoken="Here is what the holder looks like.", text="Here is what the holder looks like.")
SECOND_ASIDES = ("And what the last run gave.", "And checking the last probe.")


@dataclass(frozen=True)
class Shape:
    asked_work: bool
    script: tuple[ToolCalls | Reply, ...]
    seconds: float
    windows: int = 0
    resumed_after_s: float | None = None


def read_then_last(n: int, said: str, second: str) -> ToolCalls:
    return round_of(n, (READ, said), (LAST, second))


SHAPES = (
    Shape(False, (one(0, READ, "Looking at how the holder is built."), ANSWER), 10.0),
    Shape(True, (read_then_last(0, "Sorting the notes for the gate.", SECOND_ASIDES[0]), one(1, EDIT, "Reordering."),
                 FINAL), 15.0),
    Shape(False, (one(0, READ, "Reading the plan back."), ANSWER), 20.0),
    Shape(True, (read_then_last(0, "Making the clip for the holder.", SECOND_ASIDES[1]),
                 one(1, RUN, "Building the clip."), one(2, EDIT, "Fitting it in."), FINAL), 20.0),
    Shape(True, (*(one(n, RUN, f"Building part {n}.") for n in range(4)), FINAL), 100.0),
    Shape(True, (one(1, EDIT, "Finishing the gate."), FINAL), 20.0, resumed_after_s=60.0),
    Shape(True, (one(0, RUN, "Building the latch."), PROMISE, STOOD), 305.0, windows=2),
    Shape(False, (ANSWER,), 0.0),
    Shape(False, (one(0, READ, "Checking the lid."), ANSWER), 12.0),
    Shape(False, (one(0, READ, "Checking the cord."), ANSWER), 25.0),
)


@dataclass
class Played:
    shape: Shape
    answer: Answer
    held: list[str]
    changes: int
    seconds: float
    closed: str
    resumed_deadline: bool


def after_one_build() -> Progress:
    return Progress((*HISTORY, one(0, RUN), ToolResults((ToolResult("r0c0", "ok"),))), 1, 1)


async def play(rig: Rig, shape: Shape, log: Logged) -> Played:
    started = rig.clock.now
    rig.model.script = list(shape.script)
    base = replace(checkpoint(), windows=shape.windows, worked_s=shape.resumed_after_s or 0.0)
    if shape.resumed_after_s is None:
        run = await drive(rig, brainstorm(), seconds=shape.seconds, steps=rig.saved(base), started=started)
        got, held, changes = run.answer, run.held, run.tools.changes()
    else:
        tools = Timed(rig.clock, shape.seconds)
        steps = Saved(Claim(77, 5, "other"), loads(dumps(base)))
        got = await resumed(after_one_build(), "brainstorm", SYSTEM, TOOLS, brainstorm(), CONVERSATION, tools, True,
                            started - shape.resumed_after_s, rig.clock, steps)
        held, changes = [], tools.changes() + 1
    deadline, stood = log.events("respond.deadline"), log.events("respond.stood")
    closed = "stood" if stood else "deadline" if deadline else "answer"
    return Played(shape, got, held, changes, rig.clock.now - started, closed,
                  bool(deadline) and shape.resumed_after_s is not None)


def replay(rig: Rig, capsys: pytest.CaptureFixture[str]) -> list[Played]:
    async def go() -> list[Played]:
        return [await play(rig, shape, Logged(capsys)) for shape in SHAPES]

    return settle(go())


def test_scenario_has_ten_turns_of_the_shapes_the_spec_names() -> None:
    assert len(SHAPES) == 10 and sum(s.asked_work for s in SHAPES) == 5


def test_m1_the_median_beats_47_seconds_and_fewer_than_three_of_ten_run_past_five_minutes(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    times = [p.seconds for p in replay(rig, capsys)]
    assert median(times) < 47 and sum(t > 300 for t in times) < 3


def test_m2_a_turn_under_fifteen_seconds_holds_nothing_and_no_turn_holds_more_than_one_line(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    played = replay(rig, capsys)
    assert all(len(p.held) <= 1 for p in played)
    assert all(not p.held for p in played if p.seconds < 15)
    assert sum(len(p.held) for p in played) < 9


def test_m2_the_lines_held_are_firsts_of_their_rounds(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    lines = [line for p in replay(rig, capsys) for line in p.held]
    assert lines and not set(lines) & set(SECOND_ASIDES)


def test_m3_no_answer_that_was_asked_for_work_has_no_change(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    played = replay(rig, capsys)
    assert [p.changes for p in played if p.shape.asked_work and p.changes == 0] == []


def test_m4_no_promise_is_stored_as_an_answer_and_a_stood_close_is_the_only_open_one(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    played = replay(rig, capsys)
    assert [p for p in played if not p.answer.reply.answers and p.closed != "stood"] == []
    assert all(p.answer.reply != PROMISE for p in played)
    assert [p.closed for p in played].count("stood") == 1


def test_m4_the_stood_close_is_the_turn_that_had_no_window_left(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    played = replay(rig, capsys)
    assert played[6].closed == "stood" and played[6].answer.reply == STOOD


def test_m6_no_turn_closes_on_the_deadline_because_of_the_time_it_waited_to_be_resumed(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    played = replay(rig, capsys)
    assert not any(p.resumed_deadline for p in played)
    assert played[5].answer.reply == FINAL and played[5].changes >= 2


def test_m6_the_build_still_calling_tools_at_its_deadline_took_a_window_and_answered(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    played = replay(rig, capsys)
    assert played[4].answer.reply == FINAL and played[4].closed == "answer" and played[4].changes == 4
