"""A held turn whose model cannot be reached says so once, as her turn, keeps its work, and is finished by the resume
sweep after the backoff in `inflight.json`."""

import asyncio
from dataclasses import replace

import pytest
from ashley import logs, services
from ashley.channels import inflight_config, resume
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.respond import respond
from ashley.inference.inference import InferenceUnavailable
from contract.conversations_support import POLICY, events, run, scalar
from no_silent_endings_support import CHECKING, GOOD, UNREACHABLE, World, database, settled

RETRY_S = 0.8


@pytest.fixture(autouse=True)
def short_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    short = replace(inflight_config.CONFIG, unavailable_retry_s=RETRY_S, max_attempts=3)
    monkeypatch.setattr(inflight_config, "CONFIG", short)
    monkeypatch.setattr(resume, "CONFIG", short)


def test_the_line_is_stored_once_the_work_kept_and_the_sweep_waits_out_the_backoff(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.model.play(CHECKING, InferenceUnavailable("down"), InferenceUnavailable("still down"), GOOD)

    async def go() -> None:
        async with database(world):
            out = await respond(world.inbound(medium="spoken"))
            assert out.follows
            await settled(world, 2)
            assert world.hers() == [(CHECKING.text, True), (UNREACHABLE, True)]
            assert world.work() == 1
            await asyncio.sleep(0.5)  # the claim ran out, the backoff has not
            assert await resume.sweep() == 0
            await asyncio.sleep(RETRY_S)
            assert await resume.sweep() == 1  # unreachable again: kept again, no second line
            assert world.hers() == [(CHECKING.text, True), (UNREACHABLE, True)] and world.work() == 1
            await asyncio.sleep(RETRY_S + 0.2)
            assert await resume.sweep() == 1
            assert world.work() == 0

    run(go())
    assert world.hers() == [(CHECKING.text, True), (UNREACHABLE, True), (GOOD.spoken, False)]
    ended = events(capsys.readouterr().out, "respond.ended")
    assert [(e["reason"], e["recovery"]) for e in ended] == [
        ("inference_unavailable", "told_and_kept"), ("inference_unavailable", "kept")]
    assert all(e["conversation"].isdigit() for e in ended)


def test_a_turn_unreachable_past_max_attempts_is_given_up_and_the_person_told_it_failed(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world.model.play(CHECKING, *[InferenceUnavailable("down")] * 4)

    async def go() -> None:
        async with database(world):
            await respond(world.inbound(medium="spoken"))
            await settled(world, 2)
            for _ in range(4):
                await asyncio.sleep(RETRY_S + 0.1)
                await resume.sweep()

    run(go())
    assert world.work() == 0
    assert world.hers() == [(CHECKING.text, True), (UNREACHABLE, True)]
    ended = [(e["reason"], e["recovery"]) for e in events(capsys.readouterr().out, "respond.ended")]
    assert ended[-1] == ("gave_up", "failed_shown")


def test_on_a_channel_that_takes_replies_from_the_outbox_the_line_is_queued_for_its_thread(world: World) -> None:
    world.model.play(CHECKING, InferenceUnavailable("down"))

    async def go() -> None:
        async with database(world) as db:
            services.register(Outbox, PostgresOutbox(db, 120.0, POLICY))
            try:
                await respond(replace(world.inbound(), later_by="outbox"))
                await settled(world, 2)
                await asyncio.sleep(0.2)
            finally:
                services.unregister(Outbox)

    run(go())
    assert world.hers() == [(CHECKING.text, True), (UNREACHABLE, True)]
    assert world.queued() == 1
    assert scalar(world.url, "SELECT body FROM outbox") == UNREACHABLE
