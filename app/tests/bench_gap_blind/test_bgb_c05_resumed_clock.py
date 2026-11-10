"""Contract 5: a resumed turn's deadline counts seconds of work in its window, never the time spent waiting to be
resumed (a provider error's 120 s retries included). Driven through `resume.sweep` with a real checkpoint."""

import asyncio

import pytest
from ashley import services
from ashley.channels.limits import Limits
from ashley.channels.respond import LIMITS
from ashley.inference.reply import Reply
from ashley.workshop.workshop import Workshop
from bench_tools_support import FakeWorkshop
from bgb_resume_support import after_a_call, resumed
from later_support import Logged
from respond_support import Fakes, wired as wired

REPLY = Reply(spoken="Built.", text="Built.")


@pytest.fixture
def shop(wired: Fakes) -> FakeWorkshop:
    fake = FakeWorkshop()
    services.register(Workshop, fake)
    return fake


def test_c5_the_deadline_it_is_held_against_is_the_shipped_brainstorm_one() -> None:
    assert isinstance(LIMITS["brainstorm"], Limits) and LIMITS["brainstorm"].deadline_s == 300


def test_c5_ten_seconds_worked_resumed_at_age_400_still_has_tool_rounds(
        wired: Fakes, shop: FakeWorkshop, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    wired.inference.script = [REPLY]
    assert asyncio.run(resumed(wired, worked_s=10.0, age_s=400.0)) == 1
    assert wired.inference.prompts[0].tool_choice == "auto"
    assert log.events("respond.deadline") == []


def test_c5_the_resumed_turn_is_answered_and_its_done_line_carries_the_outcome_fields(
        wired: Fakes, shop: FakeWorkshop, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    wired.inference.script = [REPLY]
    asyncio.run(resumed(wired, worked_s=10.0, age_s=458.0))
    (done,) = log.events("respond.done")
    assert done["resumed"] == "True" or done["resumed"] == "true"
    assert (done["changes"], done["closed"], done["answers"]) == ("0", "answer", "true")


def test_c5_control_seconds_of_work_still_count_against_the_deadline(
        wired: Fakes, shop: FakeWorkshop, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    wired.inference.script = [REPLY]
    asyncio.run(resumed(wired, worked_s=310.0, age_s=5.0, windows=2, progress=after_a_call()))
    assert wired.inference.prompts[0].tool_choice == "none"
    assert len(log.events("respond.deadline")) == 1
    (done,) = log.events("respond.done")
    assert done["closed"] == "deadline"
