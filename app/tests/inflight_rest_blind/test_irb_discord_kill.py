"""A Discord message whose pod dies at any step is answered exactly once (`decisions.md`, "Work in flight survives its
pod", "Discord is a bot, its Gateway a singleton"): after the claim, with its work saved, and after her turn is
stored. The window the decision documents (killed after her turn is stored and before the send returns) is pinned as
that, not as a duplicate."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import pytest
from ashley.channels import resume
from ashley.channels.discord.message import Message
from ashley.channels.discord.seen import Seen
from ashley.channels.model import Inbound, Outbound
from contract.conversations_support import run
from contract.test_inflight_resume import CLAIM_S, DONE, HANG, World, switch_on
from discord_support import DM_CHANNEL, FakeDiscord, Sent
from irb_support import Pod, Stack, dm, sends, settle_for, stack


def texts(pod: Pod) -> list[str]:
    return pod.discord.texts()


@dataclass
class Gated(Seen):
    """The real claim store, except that a settle waits forever once it is reached."""

    real: Seen
    reached: asyncio.Event = field(default_factory=asyncio.Event)

    async def claim(self, message_id: int, channel_id: int) -> bool:
        return await self.real.claim(message_id, channel_id)

    async def last(self, since: datetime) -> dict[int, int]:
        return await self.real.last(since)

    async def prune(self, before: datetime) -> int:
        return await self.real.prune(before)

    async def unsettled(self, since: datetime) -> dict[int, int]:
        return await self.real.unsettled(since)

    async def settle(self, message_id: int) -> None:
        self.reached.set()
        await asyncio.Event().wait()


class StuckSend(FakeDiscord):
    """A session whose send never returns."""

    def __init__(self) -> None:
        super().__init__()
        self.reached = asyncio.Event()

    async def send(self, channel_id: int, text: str, reply_to: int | None) -> None:
        self.sends.append(Sent(channel_id, text, reply_to))
        self.reached.set()
        await asyncio.Event().wait()


async def caught_up(s: Stack, world: World, message: Message) -> Pod:
    """A new session whose history holds `message`; it is up and has caught up."""
    pod = Pod()
    pod.discord.backlog[DM_CHANNEL] = [message]
    world.as_pod(world.second)
    await s.start(pod)
    await settle_for(0.3)
    return pod


def test_a_claim_whose_session_died_before_the_turn_loop_is_answered_once_by_the_next(world: World) -> None:
    world.second.inference.script = [DONE]
    message = dm()
    pods: list[Pod] = []

    async def go() -> None:
        async with stack(world) as s:
            assert await s.seen.claim(message.id, DM_CHANNEL)
            assert await s.unsettled() == {message.id: DM_CHANNEL}
            pods.append(await caught_up(s, world, message))
            await sends(pods[0], 1)
            await settle_for()
            await s.stop(pods[0])
            assert await s.unsettled() == {}
            pods.append(await caught_up(s, world, message))
            await s.stop(pods[1])

    run(go())
    assert texts(pods[0]) == [DONE.text] and texts(pods[1]) == []
    assert len(world.second.inference.prompts) == 1


@pytest.mark.parametrize("order", ["catch_up_first", "resumer_first"])
def test_a_message_killed_with_its_work_saved_is_answered_once_whichever_of_catch_up_and_the_resumer_comes_first(
        world: World, order: str) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]
    message = dm()
    pods: list[Pod] = [Pod(), Pod()]

    async def go() -> None:
        async with stack(world) as s:
            world.as_pod(world.first)
            await s.start(pods[0])
            pods[0].discord.incoming.put_nowait(message)
            await asyncio.wait_for(world.first.inference.asked.wait(), 5)
            await s.kill(pods[0])
            assert await s.unsettled() == {message.id: DM_CHANNEL}
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            pods[1].discord.backlog[DM_CHANNEL] = [message]
            if order == "resumer_first":
                assert await resume.sweep() == 1
            await s.start(pods[1])
            await settle_for(0.3)
            assert texts(pods[1]) in ([], [DONE.text])
            if order == "catch_up_first":
                assert texts(pods[1]) == [], "its work is another runner's to finish"
                assert await resume.sweep() == 1
            assert await resume.sweep() == 0
            await sends(pods[1], 1)
            await settle_for()
            await s.stop(pods[1])
            assert await s.outbox.take("") == []
            assert await s.unsettled() == {}

    run(go())
    assert texts(pods[0]) == [] and texts(pods[1]) == [DONE.text]
    assert pods[1].discord.sends[0].channel_id == DM_CHANNEL
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []
    assert len(world.second.inference.prompts) == 1


def test_a_message_killed_before_it_was_settled_but_after_her_turn_was_stored_gets_no_second_answer(world: World) -> None:
    world.first.inference.script = [DONE]
    world.second.inference.script = [DONE]
    message = dm()
    pods: list[Pod] = []

    async def go() -> None:
        async with stack(world) as s:
            gate = Gated(s.seen)
            first = Pod()
            world.as_pod(world.first)
            await s.start(first, gate)
            first.discord.incoming.put_nowait(message)
            await asyncio.wait_for(gate.reached.wait(), 5)
            await s.kill(first)
            assert await s.counts() == (1, 1)
            assert await s.unsettled() == {message.id: DM_CHANNEL}
            pods.append(await caught_up(s, world, message))
            await s.stop(pods[0])
            assert await s.unsettled() == {}

    run(go())
    assert texts(pods[0]) == [], "the documented window: stored, never sent, never answered twice"
    assert world.second.inference.prompts == []


def test_a_message_killed_while_its_reply_was_being_sent_is_settled_and_not_handed_in_again(world: World) -> None:
    world.first.inference.script = [DONE]
    world.second.inference.script = [DONE]
    message = dm()
    pods: list[Pod] = []

    async def go() -> None:
        async with stack(world) as s:
            first = Pod(StuckSend())
            world.as_pod(world.first)
            await s.start(first)
            first.discord.incoming.put_nowait(message)
            assert isinstance(first.discord, StuckSend)
            await asyncio.wait_for(first.discord.reached.wait(), 5)
            await s.kill(first)
            assert await s.unsettled() == {}
            pods.append(await caught_up(s, world, message))
            await s.stop(pods[0])

    run(go())
    assert texts(pods[0]) == [] and world.second.inference.prompts == []


def test_an_answered_and_settled_message_is_not_handed_in_by_a_later_session(world: World) -> None:
    world.first.inference.script = [DONE]
    world.second.inference.script = [DONE]
    message = dm()
    pods: list[Pod] = []

    async def go() -> None:
        async with stack(world) as s:
            first = Pod()
            world.as_pod(world.first)
            await s.start(first)
            first.discord.incoming.put_nowait(message)
            await sends(first, 1)
            await settle_for()
            await s.stop(first)
            pods.extend([first, await caught_up(s, world, message)])
            await s.stop(pods[1])
            assert await s.counts() == (1, 1)

    run(go())
    assert texts(pods[0]) == [DONE.text] and texts(pods[1]) == []
    assert world.second.inference.prompts == []


def test_a_claim_is_settled_when_the_turn_loop_raises_something_unexpected(world: World) -> None:
    pod = Pod()

    async def broken(inbound: Inbound) -> Outbound:
        raise RuntimeError("boom")

    async def go() -> None:
        async with stack(world) as s:
            await s.start(pod, respond=broken)
            pod.discord.incoming.put_nowait(dm())
            await settle_for(0.3)
            assert await s.unsettled() == {}
            await s.stop(pod)

    run(go())
    assert pod.discord.sends == []


def test_two_messages_in_one_channel_are_two_turns_with_two_answers(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    pod = Pod()

    async def go() -> None:
        async with stack(world) as s:
            world.as_pod(world.first)
            await s.start(pod)
            for sequence in (1, 2):
                pod.discord.incoming.put_nowait(dm(sequence))
                await sends(pod, sequence)
            await s.stop(pod)
            assert await s.counts() == (2, 2)

    run(go())
