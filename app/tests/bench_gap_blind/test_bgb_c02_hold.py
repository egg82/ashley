"""Contract 2: on a brainstorm turn no held line goes out before 15 s of work; spoken kinds keep their short hold."""

import json
from importlib import resources

import pytest
from ashley.channels import limits as limits_module
from ashley.conversations.model import Kind
from ashley.channels.respond import LIMITS
from bgb_support import FINAL, READ, Rig, brainstorm, drive, one
from contract.inference_support import settle

SAID = "Working out the clip for you."


def test_c2_shipped_brainstorm_holds_after_fifteen_seconds_and_the_others_keep_theirs() -> None:
    shipped = limits_module.load()
    assert shipped["brainstorm"].hold_after_s == 15
    assert shipped["chat"].hold_after_s == 6
    assert shipped["command"].hold_after_s == 4
    assert LIMITS["brainstorm"].hold_after_s == 15


def test_c2_the_data_file_says_the_same_as_the_loaded_limits() -> None:
    raw = json.loads(resources.files("ashley.channels").joinpath("turns.json").read_text())
    assert raw["brainstorm"]["hold_after_s"] == 15 and raw["chat"]["hold_after_s"] == 6


def test_c2_a_brainstorm_turn_with_ten_seconds_of_work_holds_nothing(rig: Rig) -> None:
    rig.model.script = [one(0, READ, SAID), one(1, READ, SAID), FINAL]
    got = settle(drive(rig, brainstorm(), seconds=5.0))
    assert got.held == [] and got.answer.reply == FINAL


def test_c2_a_brainstorm_turn_past_fifteen_seconds_of_work_holds_one_line_about_the_work(rig: Rig) -> None:
    rig.model.script = [one(0, READ, SAID), one(1, READ, "Second."), one(2, READ, "Third."), FINAL]
    got = settle(drive(rig, brainstorm(), seconds=20.0))
    assert got.held == [SAID]


def test_c2_a_turn_with_no_aside_past_fifteen_seconds_holds_nothing(rig: Rig) -> None:
    rig.model.script = [one(0, READ, None), one(1, READ, None), one(2, READ, None), FINAL]
    got = settle(drive(rig, brainstorm(), seconds=30.0))
    assert got.held == []


@pytest.mark.parametrize(("kind", "seconds", "held"), [("chat", 7.0, 1), ("chat", 3.0, 0), ("command", 5.0, 1),
                                                        ("command", 2.0, 0)])
def test_c2_spoken_kinds_keep_the_short_hold(rig: Rig, kind: Kind, seconds: float, held: int) -> None:
    rig.model.script = [one(0, READ, SAID), FINAL]
    got = settle(drive(rig, limits_module.load()[kind], seconds=seconds, kind=kind))
    assert len(got.held) == held
