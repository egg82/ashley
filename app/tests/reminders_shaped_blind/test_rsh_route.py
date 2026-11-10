"""Which route a fired reminder takes, through the real turn loop and the push singleton: a phone reminder is pushed to its
person alone whatever Initiative or her reply says (it was asked for), a quiet one runs its turn, stores her answer and
pushes nothing and is never listed, and a deposit's reminder is no different from one set by a time, however it was stored."""

from dataclasses import replace
from typing import Literal

import pytest
from ashley.channels.wake import runner
from ashley.initiative.initiative import NullInitiative
from contract.conversations_support import run
from contract.test_inflight_resume import World
from rsh_support import DONE, LANDED, RULE, SILENT, Flow, Route, flow

How = Literal["by_time", "fired_by_deposit"]
HOWS: tuple[How, ...] = ("by_time", "fired_by_deposit")


async def make(f: Flow, how: How, route: Route, judged: bool = False) -> None:
    landed = replace(LANDED, judged=judged)
    if how == "by_time":
        await f.wakes.schedule(f.reminder(route=route))
    else:
        await f.arm_then_fire(route, landed)


@pytest.mark.parametrize("how", HOWS)
def test_a_phone_reminder_is_pushed_to_its_person_alone_with_her_answer_stored(world: World, how: How) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with flow(world) as f:
            await make(f, how, "phone")
            assert await runner.sweep() >= 1
            assert await f.pushes() == [f"push:{f.alana}"]
            assert f.hers() == [DONE.text]
            assert f.outbox() == 0

    run(go())


@pytest.mark.parametrize("how", HOWS)
def test_a_quiet_reminder_runs_its_turn_stores_the_answer_and_pushes_nothing_and_is_not_listed(world: World, how: How) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with flow(world) as f:
            await make(f, how, "quiet")
            assert await runner.sweep() >= 1
            assert len(world.first.inference.prompts) == 1
            assert f.hers() == [DONE.text]
            assert await f.pushes() == []
            assert await f.listed() == []
            assert f.outbox() == 0

    run(go())


@pytest.mark.parametrize("how", HOWS)
def test_a_phone_reminder_goes_out_when_initiative_would_keep_quiet(world: World, how: How) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with flow(world, NullInitiative()) as f:
            await make(f, how, "phone")
            await runner.sweep()
            assert await f.pushes() == [f"push:{f.alana}"]
            assert f.hers() == [DONE.text]

    run(go())


@pytest.mark.parametrize("how", HOWS)
def test_a_phone_reminder_goes_out_though_her_reply_says_it_is_not_worth_saying(world: World, how: How) -> None:
    world.first.inference.script = [SILENT]

    async def go() -> None:
        async with flow(world) as f:
            await make(f, how, "phone")
            await runner.sweep()
            assert await f.pushes() == [f"push:{f.alana}"]
            assert f.hers() == [SILENT.text]

    run(go())


@pytest.mark.parametrize("how", ["fired_by_deposit"])
def test_a_deposit_reminder_that_lets_her_judge_stays_quiet_when_she_finds_nothing_worth_saying(world: World, how: How) -> None:
    world.first.inference.script = [SILENT]

    async def go() -> None:
        async with flow(world) as f:
            await make(f, how, "phone", judged=True)
            await runner.sweep()
            assert await f.pushes() == []
            assert SILENT.text not in " ".join(f.hers())

    run(go())


@pytest.mark.parametrize("how", ["fired_by_deposit"])
def test_a_deposit_reminder_that_lets_her_judge_is_pushed_when_she_has_something_to_say(world: World, how: How) -> None:
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with flow(world) as f:
            await make(f, how, "phone", judged=True)
            await runner.sweep()
            assert await f.pushes() == [f"push:{f.alana}"]
            assert f.hers() == [DONE.text]

    run(go())


@pytest.mark.parametrize("how", HOWS)
def test_a_reminder_for_sam_set_by_alana_takes_the_same_route_to_sam(world: World, how: How) -> None:
    world.first.inference.script = [DONE, DONE]

    async def go() -> None:
        async with flow(world) as f:
            if how == "by_time":
                await f.wakes.schedule(replace(f.reminder(route="quiet"), person_id=f.sam))
                await f.wakes.schedule(replace(f.reminder(route="phone"), person_id=f.sam))
            else:
                for route in ("quiet", "phone"):
                    armed = await f.deposits.arm(replace(f.reminder(route=route), person_id=f.sam), RULE)
                    assert await f.deposits.fire(armed, f"tx-{route}", LANDED) is True
            await runner.sweep()
            assert await f.pushes() == [f"push:{f.sam}"]

    run(go())
