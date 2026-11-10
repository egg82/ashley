"""Steering on a bench: a message sent while her turn has work in flight starts no turn of its own; the running turn is
handed it before its next step, and she gives one reply covering both. Chat keeps parallel turns."""

from ashley.channels.respond import respond
from ashley.inference.model import Message, ToolResults
from bhb_support import World, pods, reply, said, switch_on
from contract.conversations_support import run


def bench_talk(w: World) -> list[tuple[str, str]]:
    return [(a, t) for a, t, _ in w.talk()]


def test_a_message_during_a_round_starts_no_turn_and_is_handed_to_the_next_step(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            answers: list[object] = []

            async def second_message() -> None:
                answers.append(await world.from_pod(2, world.bench_say("and make it dim")))

            world.tools.during = second_message
            world.model.play(switch_on(), reply("Lamp on, and dimmed."))
            out = await respond(world.bench_say("turn on the lamp"))
            assert out.body == "Lamp on, and dimmed."
            assert world.model.steps == 2, "the second message must not have started a turn"
            assert said(world.model.prompts[1]) == ["Alana just said: and make it dim"]
            assert not said(world.model.prompts[0])
            pending = answers[0]
            assert getattr(pending, "follows") is True and getattr(pending, "body") == ""
            assert bench_talk(world) == [("person", "turn on the lamp"), ("person", "and make it dim"),
                                         ("ashley", "Lamp on, and dimmed.")]
            assert world.work() == 0

    run(go())


def test_the_handed_message_arrives_after_the_round_s_results_and_before_the_step(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def second_message() -> None:
                await world.from_pod(2, world.bench_say("dim it"))

            world.tools.during = second_message
            world.model.play(switch_on(), reply("done"))
            await respond(world.bench_say("lamp"))
            entries = world.model.prompts[1].messages
            kinds = [type(e) for e in entries]
            assert ToolResults in kinds
            assert kinds.index(ToolResults) < max(i for i, e in enumerate(entries)
                                                  if isinstance(e, Message) and "dim it" in e.text)

    run(go())


def test_several_messages_in_a_row_are_handed_in_order_and_answered_once(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def three() -> None:
                for text in ("first extra", "second extra", "third extra"):
                    out = await world.from_pod(2, world.bench_say(text))
                    assert out.follows and out.body == ""

            world.tools.during = three
            world.model.play(switch_on(), reply("all four handled"))
            out = await respond(world.bench_say("start"))
            assert out.body == "all four handled"
            assert world.model.steps == 2
            assert said(world.model.prompts[1]) == ["Alana just said: first extra", "Alana just said: second extra",
                                                    "Alana just said: third extra"]
            assert world.hers() == ["all four handled"]

    run(go())


def test_messages_in_different_rounds_are_each_handed_to_the_step_after_theirs(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def later_round() -> None:
                await world.from_pod(2, world.bench_say("during two"))

            async def first_round() -> None:
                await world.from_pod(2, world.bench_say("during one"))
                world.tools.during = later_round

            world.tools.during = first_round
            world.model.play(switch_on("c1"), switch_on("c2"), reply("both heard"))
            await respond(world.bench_say("go"))
            prompts = world.model.prompts
            assert said(prompts[1]) == ["Alana just said: during one"]
            assert said(prompts[2]) == ["Alana just said: during one", "Alana just said: during two"]
            assert world.hers() == ["both heard"]

    run(go())


def test_a_message_after_the_turn_s_work_is_gone_starts_a_turn_of_its_own(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            world.model.play(reply("first answer"), reply("second answer"))
            assert (await respond(world.bench_say("one"))).body == "first answer"
            assert world.work() == 0
            out = await respond(world.bench_say("two"))
            assert (out.body, out.follows) == ("second answer", False)
            assert world.model.steps == 2
            assert bench_talk(world) == [("person", "one"), ("ashley", "first answer"), ("person", "two"),
                                         ("ashley", "second answer")]

    run(go())


def test_chat_keeps_parallel_turns(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            seen: list[str] = []

            async def other_chat_message() -> None:
                out = await world.from_pod(2, world.chat_say("what time is it"))
                seen.append(out.body)

            world.tools.during = other_chat_message
            world.model.play(switch_on(), reply("It is noon."), reply("Lamp on."))
            first = await respond(world.chat_say("turn on the lamp"))
            assert seen == ["It is noon."], "the second chat message answers on its own, not pending"
            assert first.body == "Lamp on."
            assert not said(world.model.prompts[2])
            chat = world.talk(world.chat_say("x").thread)
            assert [(a, t) for a, t, _ in chat if a == "ashley"] == [("ashley", "It is noon."), ("ashley", "Lamp on.")]

    run(go())


def test_a_bench_message_while_nothing_runs_there_is_not_pending_even_with_chat_busy(world: World) -> None:
    async def go() -> None:
        async with pods(world):
            async def bench_message() -> None:
                out = await world.from_pod(2, world.bench_say("on the bench"))
                assert out.body == "bench answer" and not out.follows

            world.tools.during = bench_message
            world.model.play(switch_on(), reply("bench answer"), reply("chat answer"))
            await respond(world.chat_say("a chat turn running"))
            assert world.hers(world.bench_say("x").thread) == ["bench answer"]
            assert not said(world.model.prompts[2])

    run(go())
