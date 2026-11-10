"""A model out of reach after the held line: she says so once and the work is kept for the resume sweep, each retry an
attempt, until it is given up and the screens are told it failed."""

import pytest
from ashley.channels import resume, unsaid
from ashley.channels.inflight_config import CONFIG
from ashley.channels.respond import respond
from ashley.inference.inference import InferenceUnavailable
from ashley.live.events import TurnFailed
from contract.conversations_support import run
from later_support import Logged
from nse_blind_support import CHECKING, DONE, World, database, until

HELD = (CHECKING.text, True)
TOLD = (unsaid.UNREACHABLE, True)


async def _begun(world: World) -> None:
    """The turn run to the point her thinking was out of reach after the held line."""
    out = await respond(world.inbound(medium="spoken"))
    assert out.follows
    await until(lambda: len(world.hers()) >= 2)


def test_she_says_once_she_cannot_reach_her_thinking_and_keeps_the_work(world: World,
                                                                        capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.model.script = [CHECKING, InferenceUnavailable("down")]

    async def go() -> None:
        async with database(world):
            await _begun(world)
            assert await resume.sweep() == 0

    run(go())
    assert world.hers() == [HELD, TOLD]
    assert world.work() == 1
    assert CONFIG.unavailable_retry_s - 30 < world.claim_left_s() <= CONFIG.unavailable_retry_s + 1
    assert [e for e in world.live.published if isinstance(e, TurnFailed)] == []
    assert [(e["reason"], e["recovery"]) for e in logged.events("respond.ended")] == [
        ("inference_unavailable", "told_and_kept")]


def test_the_kept_work_is_finished_by_the_sweep_once_its_hold_runs_out(world: World) -> None:
    world.model.script = [CHECKING, InferenceUnavailable("down"), DONE]

    async def go() -> None:
        async with database(world):
            await _begun(world)
            await world.expire()
            assert await resume.sweep() == 1
            assert await resume.sweep() == 0

    run(go())
    assert world.hers() == [HELD, TOLD, (DONE.text, False)]
    assert world.work() == 0


def test_the_line_is_not_said_again_on_a_retry_that_is_still_out_of_reach(world: World,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    world.model.script = [CHECKING, InferenceUnavailable("down"), InferenceUnavailable("still down")]

    async def go() -> None:
        async with database(world):
            await _begun(world)
            await world.expire()
            assert await resume.sweep() == 1

    run(go())
    assert world.hers() == [HELD, TOLD]
    assert world.work() == 1
    assert CONFIG.unavailable_retry_s - 30 < world.claim_left_s() <= CONFIG.unavailable_retry_s + 1
    assert [e["recovery"] for e in logged.events("respond.ended")] == ["told_and_kept", "kept"]


def test_past_max_attempts_the_work_is_given_up_and_the_screens_are_told_it_failed(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logged = Logged(capsys)
    rounds = CONFIG.max_attempts + 3
    world.model.script = [CHECKING, *[InferenceUnavailable("down") for _ in range(rounds)]]
    sweeps: list[int] = []

    async def go() -> None:
        async with database(world):
            await _begun(world)
            while world.work() and len(sweeps) < rounds:
                await world.expire()
                sweeps.append(await resume.sweep())

    run(go())
    assert world.work() == 0
    assert len(sweeps) <= CONFIG.max_attempts
    assert world.hers() == [HELD, TOLD]
    failed = [e for e in world.live.published if isinstance(e, TurnFailed)]
    assert [f.why for f in failed] == ["unavailable"]
    assert [(e["reason"], e["recovery"]) for e in logged.events("respond.ended")][-1] == ("gave_up", "failed_shown")
    assert len(world.model.calls) <= 1 + CONFIG.max_attempts
