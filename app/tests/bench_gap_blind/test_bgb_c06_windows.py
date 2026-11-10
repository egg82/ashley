"""Contract 6 and the checkpoint it is counted in: a brainstorm turn still calling tools at deadline_s takes a fresh
window, at most `windows` times, counted in its checkpoint so any pod that resumes it sees the same count."""

import json
from dataclasses import replace
from importlib import resources

import pytest
from ashley.channels import limits as limits_module
from ashley.channels.checkpoint import Checkpoint, dumps, loads
from ashley.channels.inflight import Saved
from ashley.channels.tool_loop import Progress, resumed
from ashley.conversations.inflight import Claim
from ashley.inference.model import ToolResult, ToolResults
from bgb_support import CONVERSATION, FINAL, HISTORY, SYSTEM, TOOLS, Rig, Timed, brainstorm, drive, one
from contract.inference_support import settle
from inflight_blind.ifb_checkpoint_support import checkpoint
from later_support import Logged

DEADLINE = 300.0


def shipped_turns() -> dict[str, dict[str, object]]:
    return json.loads(resources.files("ashley.channels").joinpath("turns.json").read_text())


def test_c6_shipped_windows_are_two_for_brainstorm_and_none_elsewhere() -> None:
    shipped = limits_module.load()
    assert (shipped["brainstorm"].windows, shipped["chat"].windows, shipped["command"].windows) == (2, 0, 0)


def test_c6_windows_parse_from_the_data_and_refuse_a_negative_count() -> None:
    raw = shipped_turns()
    raw["brainstorm"]["windows"] = 3
    assert limits_module.parse(raw)["brainstorm"].windows == 3
    raw["brainstorm"]["windows"] = -1
    with pytest.raises(ValueError):
        limits_module.parse(raw)


def test_c6_a_turn_still_calling_tools_at_the_deadline_takes_a_window_and_answers(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    rig.model.script = [one(0), one(1), one(2), one(3), FINAL]
    got = settle(drive(rig, brainstorm(deadline_s=DEADLINE), seconds=100.0, hold=False, steps=rig.saved()))
    assert got.answer.reply == FINAL and rig.model.choices == ["auto"] * 5
    assert log.events("respond.deadline") == []
    (line,) = log.events("respond.window")
    assert line["conversation"] == "7" and line["windows"] == "1" and {"rounds", "duration_ms"} <= set(line)


def test_c6_the_window_is_saved_with_its_clock_restarted_before_the_next_step(rig: Rig) -> None:
    rig.model.script = [one(0), one(1), one(2), one(3), FINAL]
    settle(drive(rig, brainstorm(deadline_s=DEADLINE), seconds=100.0, hold=False, steps=rig.saved()))
    before_window, after_window = rig.model.saved_at_step[2], rig.model.saved_at_step[3]
    assert before_window is not None and before_window.windows == 0 and before_window.worked_s > 0
    assert after_window is not None and after_window.windows == 1 and after_window.worked_s == 0.0


def test_c6_at_most_the_configured_windows_are_taken_then_it_closes_as_before(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    rig.model.script = [*(one(n) for n in range(9)), FINAL]
    got = settle(drive(rig, brainstorm(deadline_s=DEADLINE), seconds=100.0, hold=False, steps=rig.saved()))
    assert got.answer.reply == FINAL
    assert rig.model.choices == ["auto"] * 9 + ["none"]
    assert len(log.events("respond.window")) == 2 and len(log.events("respond.deadline")) == 1
    assert rig.store.last().windows == 2


def test_c6_a_kind_with_no_windows_closes_at_its_deadline(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    rig.model.script = [one(0), one(1), one(2), FINAL]
    chat = replace(limits_module.load()["chat"], deadline_s=250.0, hold_after_s=1e9)
    settle(drive(rig, chat, seconds=100.0, hold=False, steps=rig.saved(), kind="chat"))
    assert rig.model.choices == ["auto", "auto", "auto", "none"]
    assert log.events("respond.window") == []


def resumed_at_deadline(rig: Rig, windows: int, capsys: pytest.CaptureFixture[str]) -> Logged:
    """A turn another pod picks up from a saved checkpoint that holds `windows`, 400 s of work into its window."""
    log = Logged(capsys)
    asked = one(0)
    entries = (*HISTORY, asked, ToolResults((ToolResult("r0c0", "ok"),)))
    steps = Saved(Claim(77, 5, "other"), loads(dumps(replace(checkpoint(), windows=windows))))
    tools = Timed(rig.clock, 1.0)
    settle(resumed(Progress(entries, 1, 1), "brainstorm", SYSTEM, TOOLS, brainstorm(deadline_s=DEADLINE),
                   CONVERSATION, tools, False, rig.clock.now - 400.0, rig.clock, steps))
    return log


def test_c6_a_pod_resuming_a_turn_with_no_window_left_sees_that_and_closes(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    rig.model.script = [FINAL]
    log = resumed_at_deadline(rig, 2, capsys)
    assert rig.model.choices == ["none"] and log.events("respond.window") == []


def test_c6_a_pod_resuming_a_turn_with_one_window_left_takes_it(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    rig.model.script = [FINAL]
    log = resumed_at_deadline(rig, 1, capsys)
    assert rig.model.choices == ["auto"] and len(log.events("respond.window")) == 1
    assert rig.store.last().windows == 2


def test_c6_a_checkpoint_carries_worked_s_and_windows_through_its_json() -> None:
    fresh = checkpoint()
    assert (fresh.worked_s, fresh.windows) == (0.0, 0)
    back = loads(dumps(replace(fresh, worked_s=12.5, windows=2)))
    assert (back.worked_s, back.windows) == (12.5, 2)


def test_c6_a_checkpoint_saved_before_these_fields_loads_with_none_worked_and_no_window() -> None:
    raw = json.loads(dumps(replace(checkpoint(), worked_s=9.0, windows=1)))
    del raw["worked_s"], raw["windows"]
    old: Checkpoint = loads(json.dumps(raw))
    assert (old.worked_s, old.windows) == (0.0, 0)


def test_c6_steps_record_worked_seconds_and_a_window_in_the_saved_checkpoint(rig: Rig) -> None:
    steps = rig.saved(replace(checkpoint(), worked_s=40.0))

    async def go() -> None:
        await steps.worked(12.5)
        assert rig.store.last().worked_s == 12.5
        await steps.windowed()

    settle(go())
    assert (rig.store.last().windows, rig.store.last().worked_s) == (1, 0.0)


def test_c6_every_step_saves_the_seconds_worked_so_far(rig: Rig) -> None:
    rig.model.script = [one(0), one(1), FINAL]
    settle(drive(rig, brainstorm(), seconds=30.0, hold=False, steps=rig.saved()))
    worked = [loads(t).worked_s for t in rig.store.saved]
    assert max(worked) >= 30.0 and max(worked) <= 61.0
