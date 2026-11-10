"""A memory act after a Discord reply (forget, correction) happens exactly once across kills: recorded before it runs,
carried out by a resumer that finds it unbegun, never repeated once begun, and skipped past `max_attempts`."""

import asyncio

import pytest
from ashley import services
from ashley.channels import resume
from ashley.conversations.inflight import InFlight
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import CLAIM_S, HANG, World, switch_on
from contract.test_inflight_resume_memory import FACT, FORGET, DownAfterFinish, OneFact, settled
from contract.test_inflight_resume_memory import memory as memory
from irb_support import Pod, Stack, dm, sends, stack


def work_rows(world: World) -> int:
    return int(scalar(world.url, "SELECT count(*) FROM turn_work"))


async def killed_mid_turn(world: World, s: Stack, pod: Pod) -> None:
    """Pod one starts the Discord message and dies in its tool loop, work saved, nothing answered."""
    world.first.inference.script = [switch_on(), HANG]
    world.as_pod(world.first)
    await s.start(pod)
    pod.discord.incoming.put_nowait(dm())
    await asyncio.wait_for(world.first.inference.asked.wait(), 5)
    await s.kill(pod)
    await asyncio.sleep(CLAIM_S * 1.5)
    world.as_pod(world.second)


def test_a_resumed_discord_answer_with_a_forget_is_queued_once_and_the_forget_made_once(
        world: World, memory: OneFact) -> None:
    world.second.inference.script = [FORGET]
    pods = [Pod(), Pod()]

    async def go() -> None:
        async with stack(world) as s:
            await killed_mid_turn(world, s, pods[0])
            assert await resume.sweep() == 1
            await settled()
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await resume.sweep() == 0
            await s.start(pods[1])
            await sends(pods[1], 1)
            await settled()
            await s.stop(pods[1])

    run(go())
    assert memory.forgot == [FACT]
    assert pods[1].discord.texts() == [FORGET.text] and world.hers() == [FORGET.text]
    assert work_rows(world) == 0


def test_a_forget_cut_off_while_it_ran_after_a_resumed_answer_is_not_made_again_nor_the_answer_queued_again(
        world: World, memory: OneFact) -> None:
    world.second.inference.script = [FORGET]
    memory.hang = True
    pods = [Pod(), Pod()]

    async def go() -> None:
        async with stack(world) as s:
            await killed_mid_turn(world, s, pods[0])
            resumer = asyncio.create_task(resume.sweep())
            await asyncio.wait_for(memory.reached.wait(), 5)
            (running,) = memory.tasks
            assert running is not None
            running.cancel()
            await resumer
            await settled()
            memory.hang = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.first)
            await resume.sweep()
            await settled()
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await resume.sweep() == 0
            await s.start(pods[1])
            await sends(pods[1], 1)
            await settled()
            await s.stop(pods[1])

    run(go())
    assert memory.forgot == [FACT]
    assert pods[1].discord.texts() == [FORGET.text] and world.hers() == [FORGET.text]
    assert work_rows(world) == 0


def test_a_forget_whose_runner_stopped_before_recording_it_is_made_once_by_the_resumer_with_the_answer_sent_once(
        world: World, memory: OneFact) -> None:
    world.first.inference.script = [FORGET]
    pod = Pod()

    async def go() -> None:
        async with stack(world) as s:
            outage = DownAfterFinish(services.get(InFlight))
            services.register(InFlight, outage)
            world.as_pod(world.first)
            await s.start(pod)
            pod.discord.incoming.put_nowait(dm())
            await sends(pod, 1)
            await settled()
            assert memory.forgot == []
            outage.down = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await resume.sweep() == 1
            await settled()
            assert await resume.sweep() == 0
            await s.stop(pod)

    run(go())
    assert memory.forgot == [FACT]
    assert pod.discord.texts() == [FORGET.text] and world.hers() == [FORGET.text]
    assert world.second.inference.prompts == []


def test_a_forget_past_max_attempts_is_skipped_and_not_looked_for_again(
        world: World, memory: OneFact, monkeypatch: pytest.MonkeyPatch) -> None:
    world.first.inference.script = [FORGET]
    pod = Pod()
    monkeypatch.setattr(resume, "CONFIG", resume.Config(CLAIM_S, 1.0, 1, 10))

    async def go() -> None:
        async with stack(world) as s:
            outage = DownAfterFinish(services.get(InFlight))
            services.register(InFlight, outage)
            world.as_pod(world.first)
            await s.start(pod)
            pod.discord.incoming.put_nowait(dm())
            await sends(pod, 1)
            await settled()
            outage.down = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await resume.sweep() == 1
            await settled()
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await resume.sweep() == 0
            await s.stop(pod)

    run(go())
    assert memory.forgot == []
    assert world.hers() == [FORGET.text] and world.second.inference.prompts == []
