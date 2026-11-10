"""A pod killed in the middle of a steering turn: another pod resumes it from its checkpoint. A message already handed
is not handed again, one not yet handed is handed once, and every message is answered once."""

import asyncio

import pytest
from ashley.channels.respond import respond
from ashley.inference.model import Prompt, ToolCalls
from ashley.inference.reply import Reply
from bhb_support import World, hang, kill_the_turn, pods, reply, said, switch_on
from contract.conversations_support import run


def test_a_kill_after_the_final_step_hand_resumes_on_another_pod_without_handing_again(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def draft_with_a_message_sent(prompt: Prompt) -> ToolCalls | Reply:
                await world.from_pod(2, world.bench_say("late thought"))
                return reply("draft")

            async def killed_when_asked_again(prompt: Prompt) -> ToolCalls | Reply:
                kill_the_turn()
                await hang()
                raise AssertionError("unreachable")

            world.model.play(draft_with_a_message_sent, killed_when_asked_again)
            running = asyncio.create_task(respond(world.bench_say("question")))
            with pytest.raises(asyncio.CancelledError):
                await running
            assert world.work() == 1 and world.hers() == []
            assert said(world.model.prompts[0]) == [], "the message was sent after her first step began"
            world.expire_claims()
            world.model.play(reply("answer covering both"))
            assert await world.sweep(2) == 1
            assert world.hers() == ["answer covering both"]
            resumed = world.model.prompts[-1]
            assert said(resumed) == ["Alana just said: late thought"], "handed once: not lost, not handed twice"
            assert world.work() == 0
            assert await world.sweep(1) == 0
            assert world.hers() == ["answer covering both"]

    run(go())


def test_a_message_that_arrives_while_the_killed_turn_waits_for_a_runner_is_handed_to_it_once(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def killed() -> None:
                kill_the_turn()
                await hang()

            world.tools.during = killed
            world.model.play(switch_on())
            running = asyncio.create_task(respond(world.bench_say("question")))
            with pytest.raises(asyncio.CancelledError):
                await running
            world.expire_claims()
            out = await world.from_pod(2, world.bench_say("while nobody ran it"))
            assert out.follows is True and out.body == "", "the waiting turn is the bench's running turn"
            world.model.play(reply("one reply for both"))
            assert await world.sweep(2) == 1
            assert world.hers() == ["one reply for both"]
            assert said(world.model.prompts[-1]) == ["Alana just said: while nobody ran it"]
            assert world.work() == 0

    run(go())


def test_a_message_handed_before_the_kill_is_not_handed_again_by_the_resumed_turn(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def sent_during_the_round() -> None:
                await world.from_pod(2, world.bench_say("during"))

            async def killed_on_the_second_round() -> None:
                kill_the_turn()
                await hang()

            async def second_round(prompt: Prompt) -> ToolCalls | Reply:
                world.tools.during = killed_on_the_second_round
                return switch_on("c2")

            world.tools.during = sent_during_the_round
            world.model.play(switch_on("c1"), second_round)
            running = asyncio.create_task(respond(world.bench_say("question")))
            with pytest.raises(asyncio.CancelledError):
                await running
            assert said(world.model.prompts[1]) == ["Alana just said: during"]
            world.expire_claims()
            world.model.play(reply("done"))
            assert await world.sweep(2) == 1
            assert said(world.model.prompts[-1]) == ["Alana just said: during"]
            assert world.hers() == ["done"]

    run(go())
