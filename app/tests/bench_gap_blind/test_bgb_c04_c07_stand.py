"""Contracts 4 and 7: a closing reply with answers=false is never stored as her answer; with a window left it takes
one, with none left it is asked once more with `stand` and that reply is stored, whatever its field says."""

from dataclasses import replace

import pytest

from ashley.inference.model import Message
from ashley.inference.reply import Reply
from ashley.channels.tool_loop import Answer
from bgb_support import FINAL, PROMISE, STAND_SPEC_TEXT, STOOD, Rig, brainstorm, drive, one, stand_text
from contract.inference_support import settle
from inflight_blind.ifb_checkpoint_support import checkpoint
from later_support import Logged

DEADLINE = 50.0




def close_with_no_window(rig: Rig, *replies: Reply, windows: int = 2) -> Answer:
    """One 60 s call past a 50 s deadline, her windows spent; each of `replies` then answers a step."""
    rig.model.script = [one(0), *replies]
    steps = rig.saved(replace(checkpoint(), windows=windows))
    return settle(drive(rig, brainstorm(deadline_s=DEADLINE), seconds=60.0, hold=False, steps=steps,
                        started=rig.clock.now)).answer


def test_c7_a_promise_at_the_close_with_no_window_left_is_asked_again_with_stand(rig: Rig) -> None:
    got = close_with_no_window(rig, PROMISE, STOOD)
    assert got.reply == STOOD
    assert rig.model.choices == ["auto", "none", "none"]
    assert rig.model.last_text(2) == stand_text() == STAND_SPEC_TEXT


def test_c4_the_promise_is_never_the_stored_answer(rig: Rig) -> None:
    assert close_with_no_window(rig, PROMISE, STOOD).reply != PROMISE


def test_c7_the_stand_reply_is_stored_whatever_its_answers_field_says(rig: Rig) -> None:
    again = STOOD.model_copy(update={"answers": False})
    got = close_with_no_window(rig, PROMISE, again)
    assert got.reply == again and len(rig.model.asked) == 3


def test_c7_control_a_closing_reply_that_answers_is_stored_with_no_second_step(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    got = close_with_no_window(rig, FINAL)
    assert got.reply == FINAL and len(rig.model.asked) == 2
    assert log.events("respond.stood") == []


def test_c7_asking_for_the_stand_is_logged_with_the_conversation_and_rounds(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    close_with_no_window(rig, PROMISE, STOOD)
    (line,) = log.events("respond.stood")
    assert line["conversation"] == "7" and line["rounds"].isdigit()


def test_c12_the_branch_reads_the_field_not_the_words(rig: Rig) -> None:
    plain = Reply(answers=False, spoken="Okay.", text="Okay.")
    assert close_with_no_window(rig, plain, STOOD).reply == STOOD
    promising = Reply(answers=True, spoken="Give me a moment to build it.", text="Give me a moment to build it.")
    assert close_with_no_window(rig, promising).reply == promising


def test_c4_a_promise_at_a_close_with_a_window_left_is_not_stored_and_the_turn_goes_on_under_auto(
        rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    rig.model.script = [PROMISE, FINAL]
    steps = rig.saved(checkpoint())
    got = settle(drive(rig, brainstorm(deadline_s=300.0), hold=False, steps=steps, started=rig.clock.now - 400.0))
    assert got.answer.reply == FINAL
    assert rig.model.choices == ["none", "auto"]
    assert rig.store.last().windows == 1
    assert len(log.events("respond.window")) == 1 and log.events("respond.stood") == []
    said = [m.text for p in rig.model.asked for m in p.messages if isinstance(m, Message)]
    assert stand_text() not in said
