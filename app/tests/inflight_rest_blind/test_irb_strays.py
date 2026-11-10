"""Claims a session died holding that cannot become a turn she answers are settled, not answered; a turn whose channel
takes no later replies is not saved for a resumer."""

import asyncio
from dataclasses import dataclass
from typing import Any

from ashley.channels import resume
from ashley.channels.discord.route import route
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.inference.inference import InferenceUnavailable
from ashley.inference.model import Prompt, Task
from ashley.people.people import PeopleUnavailable
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, DONE, HANG, ScriptedInference, World, switch_on
from discord_support import DM_CHANNEL, GUEST_ID, snowflake, NOW, message
from irb_support import Pod, dm, sends, settle_for, stack


def test_a_stranded_claim_from_an_unmapped_account_is_settled_and_not_answered(world: World) -> None:
    stranger = message(id=snowflake(NOW, 2), channel_id=DM_CHANNEL, guild_id=None, mentions_me=False,
                       author_id=GUEST_ID)
    pod = Pod()

    async def go() -> None:
        async with stack(world) as s:
            assert await s.seen.claim(stranger.id, DM_CHANNEL)
            pod.discord.backlog[DM_CHANNEL] = [stranger]
            world.as_pod(world.second)
            await s.start(pod)
            await settle_for(0.3)
            assert await s.unsettled() == {}
            await s.stop(pod)

    run(go())
    assert pod.discord.sends == [] and world.second.inference.prompts == []
    assert world.hers() == []


def test_a_stranded_claim_whose_person_cannot_be_read_is_settled_and_not_answered(world: World) -> None:
    pod = Pod()
    message = dm()

    async def go() -> None:
        async with stack(world) as s:
            s.people.error = PeopleUnavailable()
            assert await s.seen.claim(message.id, DM_CHANNEL)
            pod.discord.backlog[DM_CHANNEL] = [message]
            world.as_pod(world.second)
            await s.start(pod)
            await settle_for(0.3)
            assert await s.unsettled() == {}
            await s.stop(pod)

    run(go())
    assert pod.discord.sends == [] and world.second.inference.prompts == []


def test_a_turn_on_a_channel_with_no_later_replies_is_not_saved_for_a_resumer(world: World) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]
    inbound = Inbound(household_id=world.who.household_id, thread="device:5", text="turn on the lamp",
                      kind="command", medium="spoken", audience="household", speaker_id=None, shared=True,
                      place="kitchen", channel="voice", later=False)

    async def go() -> None:
        async with stack(world):
            world.as_pod(world.first)
            turn = asyncio.create_task(respond(inbound))
            await asyncio.wait_for(world.first.inference.asked.wait(), 5)
            turn.cancel()
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await resume.sweep() == 0

    run(go())
    assert world.hers() == [] and world.second.inference.prompts == []


@dataclass
class Unavailable(ScriptedInference):
    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        raise InferenceUnavailable("down")


def test_a_claim_is_settled_when_the_turn_loop_could_not_answer(world: World) -> None:
    world.first.inference = Unavailable()
    pod = Pod()

    async def go() -> None:
        async with stack(world) as s:
            world.as_pod(world.first)
            await s.start(pod)
            pod.discord.incoming.put_nowait(dm())
            await sends(pod, 1)
            await settle_for()
            assert await s.unsettled() == {}
            await s.stop(pod)

    run(go())
    assert len(pod.discord.sends) == 1


def discord(world: World) -> Inbound:
    made = route(dm(), 4242, {}, world.who)
    assert made is not None
    return made


def test_a_message_handed_to_the_turn_loop_again_while_saved_or_answered_returns_pending_with_no_words(
        world: World) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stack(world):
            world.as_pod(world.first)
            turn = asyncio.create_task(respond(discord(world)))
            await asyncio.wait_for(world.first.inference.asked.wait(), 5)
            turn.cancel()
            world.as_pod(world.second)
            saved = await respond(discord(world))
            assert (saved.follows, saved.body) == (True, "")
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await resume.sweep() == 1
            answered = await respond(discord(world))
            assert (answered.follows, answered.body) == (True, "")

    run(go())
    assert world.hers() == [DONE.text] and len(world.second.inference.prompts) == 1
