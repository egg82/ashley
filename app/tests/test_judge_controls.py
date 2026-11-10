"""The model judge's controls (`ashley.memory.eval.judge.failed_controls`) can tell a trustworthy judge from a useless
one: a judge that agrees with everything, or with nothing, fails them; one that answers as each control says passes."""

import asyncio
import json
from importlib import resources

from ashley.memory.eval import judge

CONTROLS = json.loads(resources.files("ashley.memory.eval").joinpath("judge_controls.json").read_text("utf-8"))


async def _always(answer: bool, expected: str, actual: str) -> bool:
    return answer


async def _oracle(expected: str, actual: str) -> bool:
    return next(c["same"] for c in CONTROLS["controls"] if (c["expected"], c["written"]) == (expected, actual))


def test_the_controls_hold_both_verdicts() -> None:
    assert {c["same"] for c in CONTROLS["controls"]} == {True, False}


def test_a_judge_answering_as_the_controls_say_passes() -> None:
    assert asyncio.run(judge.failed_controls(_oracle)) == []


def test_a_judge_that_agrees_with_everything_fails_every_reject_control() -> None:
    failed = asyncio.run(judge.failed_controls(lambda e, a: _always(True, e, a)))
    assert len(failed) == sum(not c["same"] for c in CONTROLS["controls"]) > 0


def test_a_judge_that_agrees_with_nothing_fails_every_accept_control() -> None:
    failed = asyncio.run(judge.failed_controls(lambda e, a: _always(False, e, a)))
    assert len(failed) == sum(c["same"] for c in CONTROLS["controls"]) > 0
