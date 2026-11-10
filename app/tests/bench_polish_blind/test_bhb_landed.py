"""A turn that began in chat and moved the person's page to a bench is that bench's running turn once its ask is
carried into the bench's talk: the bench's messages steer it, her held line after the move is said in the bench's
talk after the carried ask, and she is offered `bench_run` there, never `run_code`."""

import asyncio

import pytest
from ashley.channels.respond import respond
from ashley.inference.model import Prompt, ToolCalls
from ashley.inference.reply import Reply
from bhb_support import World, finished, hang, kill_the_turn, move_to, pods, reply, said, switch_on, tool_names
from contract.conversations_support import run, scalar


def chat_thread(world: World) -> str:
    return world.chat_say("x").thread


def test_a_bench_message_during_a_landed_turn_is_handed_to_it_and_answered_in_the_bench(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            seen: list[object] = []

            async def bench_message() -> None:
                seen.append(await world.from_pod(2, world.bench_say("also dim it")))

            async def step_after_the_move(prompt: Prompt) -> ToolCalls | Reply:
                world.tools.during = bench_message
                return switch_on()

            world.model.play(move_to(world.bench.id), step_after_the_move, reply("done on the bench"))
            await respond(world.chat_say("take me to the bench and turn on the lamp"))
            assert getattr(seen[0], "follows") is True and getattr(seen[0], "body") == ""
            assert world.model.steps == 3, "the bench message started no turn of its own"
            assert said(world.model.prompts[2]) == ["Alana just said: also dim it"]
            talk = [(a, t) for a, t, _ in world.talk()]
            assert talk == [("person", "take me to the bench and turn on the lamp"), ("person", "also dim it"),
                            ("ashley", "done on the bench")]
            assert world.work() == 0

    run(go())


def test_a_landed_turn_killed_and_resumed_on_another_pod_still_takes_the_bench_message(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def killed() -> None:
                kill_the_turn()
                await hang()

            async def step_after_the_move(prompt: Prompt) -> ToolCalls | Reply:
                world.tools.during = killed
                return switch_on()

            world.model.play(move_to(world.bench.id), step_after_the_move)
            running = asyncio.create_task(respond(world.chat_say("go to the bench")))
            with pytest.raises(asyncio.CancelledError):
                await running
            world.expire_claims()
            out = await world.from_pod(2, world.bench_say("meanwhile"))
            assert out.follows is True and out.body == ""
            world.model.play(reply("one reply"))
            assert await world.sweep(2) == 1
            assert said(world.model.prompts[-1]) == ["Alana just said: meanwhile"]
            assert world.hers() == ["one reply"]
            assert world.work() == 0

    run(go())


def test_her_held_line_after_the_move_is_said_in_the_bench_talk_after_the_carried_ask(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            world.model.play(move_to(world.bench.id), reply("Let me look into that.", answers=False),
                                  reply("Here is what I found."))
            out = await respond(world.chat_say("find me a reference"))
            assert out.follows is True and out.body == "Let me look into that."
            await finished(world, 1)
            await finished(world, 1, chat_thread(world))  # the chat's link to the bench is stored after
            assert world.talk() == [("person", "find me a reference", False),
                                    ("ashley", "Let me look into that.", True),
                                    ("ashley", "Here is what I found.", False)]
            talk_id = world.thread_conversation(f"bench:{world.bench.id}")
            held, ask = (int(scalar(world.url, f"SELECT {column} FROM turns WHERE conversation_id = %s AND text = %s",
                                    (talk_id, text)))
                         for column, text in (("answers", "Let me look into that."), ("id", "find me a reference")))
            assert held == ask, "the held line in the bench's talk answers the carried ask"
            in_chat = [t for _, t, _ in world.talk(chat_thread(world))]
            assert "Let me look into that." not in in_chat
            assert in_chat[0] == "find me a reference" and in_chat[-1] == world.bench.title

    run(go())


def test_a_held_line_said_before_the_move_stays_in_chat(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            world.model.play(reply("Checking first.", answers=False), move_to(world.bench.id),
                                  reply("All done."))
            out = await respond(world.chat_say("find me a reference"))
            assert out.body == "Checking first."
            await finished(world, 1)
            await finished(world, 1, chat_thread(world))  # the chat's link to the bench is stored after
            assert world.talk() == [("person", "find me a reference", False), ("ashley", "All done.", False)]
            in_chat = world.talk(chat_thread(world))
            assert in_chat[:2] == [("person", "find me a reference", False), ("ashley", "Checking first.", True)]
            assert in_chat[-1][1] == world.bench.title

    run(go())


def test_bench_turns_are_offered_bench_run_and_never_run_code(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            world.model.play(reply("ok"))
            await respond(world.bench_say("run something"))
            names = tool_names(world.model.prompts[0])
            assert "bench_run" in names and "run_code" not in names

    run(go())


def test_chat_turns_are_offered_run_code_and_not_bench_run(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            world.model.play(reply("ok"))
            await respond(world.chat_say("run something"))
            names = tool_names(world.model.prompts[0])
            assert "run_code" in names and "bench_run" not in names

    run(go())


def test_a_turn_that_lands_mid_way_swaps_run_code_for_bench_run(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            world.model.play(move_to(world.bench.id), reply("ok"))
            await respond(world.chat_say("go to the bench and run something"))
            before, after = tool_names(world.model.prompts[0]), tool_names(world.model.prompts[1])
            assert "run_code" in before and "bench_run" not in before
            assert "bench_run" in after and "run_code" not in after

    run(go())
