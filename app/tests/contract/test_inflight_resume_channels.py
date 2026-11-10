"""Work in flight survives its pod on the channels that push (`decisions.md`, "Work in flight survives its pod"): a
Discord or voice turn whose runner is killed is resumed by another runner, and its answer is queued in the `Outbox` for
the thread exactly once, stored as her turn in the same transaction. A Discord message handed to the turn loop again
(a new session catching up on a claim its dead session never settled) is one person turn and gets one answer.

Postgres is real (Conversations, `InFlight`, `Outbox`); the model, the tools and the people are fakes, as in
`test_inflight_resume.py`."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.channels.discord.message import Message
from ashley.channels.discord.route import route
from ashley.channels.model import Inbound, Outbound
from ashley.channels.outbox import Later, Outbox, Pushed
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import ClaimLost, InFlight
from ashley.conversations.model import NewTurn
from ashley.inference.model import Prompt, Task
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue
from contract.conversations_support import POLICY, run, scalar
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.test_inflight_resume import (CLAIM_S, DONE, HANG, ScriptedInference, Switch, World, database, sweep,
                                           switch_on)
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world

DM = 2001
SATELLITE = 77
HELD = Reply(answers=False, spoken="Let me check.", text="Let me check.")


def discord(world: World, message_id: int = 9001) -> Inbound:
    sent = Message(id=message_id, channel_id=DM, guild_id=None, author_id=555, author_is_bot=False,
                   content="turn on the lamp", mentions_me=False, replies_to_me=False)
    made = route(sent, 4242, {}, world.who)
    assert made is not None
    return made


def voice(world: World) -> Inbound:
    return Inbound(household_id=world.who.household_id, thread=f"device:{SATELLITE}", text="turn on the lamp",
                   kind="command", medium="spoken", audience="household", speaker_id=None, shared=True,
                   place="kitchen", channel="voice", later=True)


@dataclass
class StuckCatalogue(Switch):
    """A tool source whose catalogue never answers: the runner dies before the turn's work is saved."""

    asked: asyncio.Event = field(default_factory=asyncio.Event)

    async def catalogue(self) -> Catalogue:
        self.asked.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@dataclass
class Stepping(ScriptedInference):
    """Records the task each step runs in, so a test can kill the one running the turn."""

    tasks: list[asyncio.Task[Any] | None] = field(default_factory=list[asyncio.Task[Any] | None])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.tasks.append(asyncio.current_task())
        return await super().step(task, prompt, output, conversation_id=conversation_id)


@asynccontextmanager
async def stores(world: World) -> AsyncGenerator[Outbox]:
    async with database(world) as db:
        services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
        try:
            yield services.get(Outbox)
        finally:
            services.unregister(Outbox)


async def killed(world: World, inbound: Inbound, reached: asyncio.Event) -> None:
    world.as_pod(world.first)
    turn = asyncio.create_task(respond(inbound))
    await asyncio.wait_for(reached.wait(), 5)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn


async def resumed(world: World) -> None:
    await asyncio.sleep(CLAIM_S * 1.5)
    world.as_pod(world.second)
    assert await sweep() == 1
    assert await sweep() == 0


def bodies(taken: list[Later]) -> list[str]:
    return [t.outbound.body for t in taken]


def people_turns(world: World) -> int:
    return int(scalar(world.url, "SELECT count(*) FROM turns WHERE author = 'person'"))


@pytest.mark.parametrize("channel", [discord, voice], ids=["discord", "voice"])
def test_a_turn_killed_after_its_change_is_answered_once_through_the_outbox(world: World, channel: object) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]
    inbound = discord(world) if channel is discord else voice(world)
    taken: list[Later] = []

    async def go() -> None:
        async with stores(world) as outbox:
            await killed(world, inbound, world.first.inference.asked)
            assert await outbox.take("") == []
            await resumed(world)
            taken.extend(await outbox.take(""))
            assert await outbox.take("") == []

    run(go())
    expected = DONE.text if inbound.medium == "text" else DONE.spoken
    assert bodies(taken) == [expected] and [t.thread for t in taken] == [inbound.thread]
    assert world.hers() == [expected]
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []


def test_a_held_discord_answer_killed_in_the_background_is_answered_once_through_the_outbox(world: World) -> None:
    stepping = Stepping([HELD, switch_on(), HANG])
    world.first.inference = stepping
    world.second.inference.script = [DONE]
    taken: list[Later] = []

    async def go() -> None:
        async with stores(world) as outbox:
            world.as_pod(world.first)
            out = await respond(discord(world))
            assert (out.follows, out.body) == (True, HELD.text)
            await asyncio.wait_for(world.first.inference.asked.wait(), 5)
            running = stepping.tasks[-1]
            assert running is not None and running is not stepping.tasks[0]
            running.cancel()
            await asyncio.sleep(0.05)
            await resumed(world)
            taken.extend(await outbox.take(""))

    run(go())
    assert bodies(taken) == [DONE.text]
    assert world.hers() == [HELD.text, DONE.text]
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []


def test_a_discord_message_handed_in_again_after_its_runner_died_before_its_work_was_saved_is_answered_once(
        world: World) -> None:
    stuck = StuckCatalogue()
    world.first.tools = stuck
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with stores(world) as outbox:
            await killed(world, discord(world), stuck.asked)
            assert await sweep() == 0, "nothing was saved for a resumer"
            world.as_pod(world.second)
            out = await respond(discord(world))
            assert (out.follows, out.body) == (False, DONE.text)
            assert await outbox.take("") == []

    run(go())
    assert people_turns(world) == 1
    assert world.hers() == [DONE.text]


def test_a_discord_message_handed_in_again_while_its_work_is_saved_or_once_answered_gets_no_second_answer(
        world: World) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]
    taken: list[Later] = []

    async def go() -> None:
        async with stores(world) as outbox:
            await killed(world, discord(world), world.first.inference.asked)
            world.as_pod(world.second)
            again = await respond(discord(world))
            assert (again.follows, again.body) == (True, ""), "its work is another runner's to finish"
            await resumed(world)
            taken.extend(await outbox.take(""))
            late = await respond(discord(world))
            assert (late.follows, late.body) == (True, ""), "it was answered"
            assert await sweep() == 0

    run(go())
    assert bodies(taken) == [DONE.text]
    assert people_turns(world) == 1
    assert world.hers() == [DONE.text]
    assert world.second.inference.prompts and len(world.second.inference.prompts) == 1


def test_another_discord_message_with_the_same_words_is_its_own_turn(world: World) -> None:
    world.first.inference.script = [DONE, DONE]

    async def go() -> None:
        async with stores(world):
            world.as_pod(world.first)
            assert (await respond(discord(world, 1))).body == DONE.text
            assert (await respond(discord(world, 2))).body == DONE.text

    run(go())
    assert people_turns(world) == 2
    assert world.hers() == [DONE.text, DONE.text]


def test_an_answer_whose_claim_was_lost_is_neither_queued_nor_stored(world: World) -> None:
    async def go() -> None:
        async with stores(world) as outbox:
            conversations = services.get(Conversations)
            started = await conversations.start(world.who.household_id, "chat", [world.who.id])
            said = await conversations.add_turn(started.id, NewTurn("person", "hi", world.who.id, "private",
                                                                    world.who.id))
            claim = await services.get(InFlight).begin(started.id, said.id, "{}")
            await asyncio.sleep(CLAIM_S * 1.5)
            assert len(await services.get(InFlight).orphaned(10)) == 1
            with pytest.raises(ClaimLost):
                await outbox.answer(claim, NewTurn("ashley", "Done.", answers=said.id),
                                    [Pushed(world.who.household_id, "discord:1", Outbound(started.id, "text", "Done."))])
            assert await outbox.take("") == []

    run(go())
    assert world.hers() == []
