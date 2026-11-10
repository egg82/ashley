"""A person's message while a turn is running on a bench steers that turn instead of starting a second (`decisions.md`,
"A message on a bench steers the running turn"): stored at once, handed to the running turn at its next step, one reply
for both; a message after the turn ended is its own turn; a runner killed with a message pending is resumed by another
that still sees it. Postgres is real (Conversations and `InFlight`); the model and tools are fakes."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from ashley import services
from ashley.channels.model import Inbound, Outbound
from ashley.channels.respond import respond
from ashley.inference.model import Message, Prompt, Task, ToolCall, ToolResult
from ashley.inference.reply import Reply
from ashley.people.model import Household, Person
from ashley.people.people import People
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.conversations_support import run
from contract.conversations_support import person
from contract.test_inflight_resume import (CLAIM_S, DONE, HANG, OnePerson, Pod, ScriptedInference, Switch, World,
                                           database, sweep, switch_on)
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world

ANOTHER = Reply(spoken="The porch light is on too.", text="The porch light is on too.")
SECOND = "and check the porch light"
SAID = f"Alana just said: {SECOND}"


def bench_turn(world: World, text: str = "turn on the lamp") -> Inbound:
    return replace(world.inbound(), text=text, steers=True)


@dataclass
class Hooked(ScriptedInference):
    """A model that runs `before[n]` first when asked its step number `n` (from 0)."""

    before: dict[int, Callable[[], Awaitable[None]]] = field(default_factory=dict[int, Callable[[], Awaitable[None]]])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        hook = self.before.get(len(self.prompts))
        if hook is not None:
            await hook()
        return await super().step(task, prompt, output, conversation_id=conversation_id)


@dataclass
class Sends(Switch):
    """The change tool, which also sends a second message while it runs."""

    during: Callable[[], Awaitable[None]] = field(default=lambda: asyncio.sleep(0))

    async def call(self, call: ToolCall) -> ToolResult:
        await self.during()
        return await super().call(call)


def said_in(prompt: Prompt) -> list[str]:
    return [e.text for e in prompt.messages if isinstance(e, Message) and e.text == SAID]


def test_a_message_while_a_tool_runs_is_handed_to_the_next_step_and_gets_no_turn_of_its_own(world: World) -> None:
    tools = Sends()
    pod = Pod(Hooked(), tools)
    world.first = pod
    pod.inference.script = [switch_on(), DONE]
    seen: list[Outbound] = []

    async def second() -> None:
        seen.append(await respond(bench_turn(world, SECOND)))

    tools.during = second

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            out = await respond(bench_turn(world))
            assert out.body == DONE.text

    run(go())
    assert [(o.follows, o.body) for o in seen] == [(True, "")]
    assert len(pod.inference.prompts) == 2 and said_in(pod.inference.prompts[1]) == [SAID]
    assert world.hers() == [DONE.text]


def test_a_message_during_the_final_step_is_answered_by_one_more_step_and_only_that_reply_is_stored(
        world: World) -> None:
    pod = Pod(Hooked(), Switch())
    world.first = pod
    pod.inference.script = [DONE, ANOTHER]

    async def second() -> None:
        await respond(bench_turn(world, SECOND))

    assert isinstance(pod.inference, Hooked)
    pod.inference.before = {0: second}

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            out = await respond(bench_turn(world))
            assert out.body == ANOTHER.text

    run(go())
    last = pod.inference.prompts[1].messages
    assert [e.text for e in last if isinstance(e, Message)][-2:] == [DONE.text, SAID]
    assert world.hers() == [ANOTHER.text]


def test_a_message_after_the_turn_ended_is_its_own_turn(world: World) -> None:
    world.first.inference.script = [DONE, ANOTHER]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            assert (await respond(bench_turn(world))).body == DONE.text
            assert (await respond(bench_turn(world, SECOND))).body == ANOTHER.text

    run(go())
    assert world.hers() == [DONE.text, ANOTHER.text]


def test_a_runner_killed_with_a_message_not_yet_handed_leaves_it_to_the_runner_that_resumes_the_turn(
        world: World) -> None:
    world.first.inference.script = [HANG]
    world.second.inference.script = [ANOTHER]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            turn = asyncio.create_task(respond(bench_turn(world)))
            await asyncio.wait_for(world.first.inference.asked.wait(), 5)
            assert (await respond(bench_turn(world, SECOND))).follows
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    assert said_in(world.second.inference.prompts[0]) == [SAID]
    assert world.hers() == [ANOTHER.text]


def test_a_runner_killed_after_handing_a_message_over_leaves_it_in_the_resumed_turn_once(world: World) -> None:
    tools = Sends()
    pod = Pod(Hooked(), tools)
    world.first = pod
    pod.inference.script = [switch_on(), HANG]
    world.second.inference.script = [ANOTHER]

    async def second() -> None:
        await respond(bench_turn(world, SECOND))

    tools.during = second

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            turn = asyncio.create_task(respond(bench_turn(world)))
            await asyncio.wait_for(pod.inference.asked.wait(), 5)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    assert said_in(world.second.inference.prompts[0]) == [SAID]
    assert world.hers() == [ANOTHER.text]


def test_a_runner_killed_after_a_final_step_hand_leaves_the_resumed_turn_its_draft_between_the_two_messages(
        world: World) -> None:
    pod = Pod(Hooked(), Switch())
    world.first = pod
    pod.inference.script = [DONE, HANG]
    world.second.inference.script = [ANOTHER]

    async def second() -> None:
        await respond(bench_turn(world, SECOND))

    assert isinstance(pod.inference, Hooked)
    pod.inference.before = {0: second}

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            turn = asyncio.create_task(respond(bench_turn(world)))
            await asyncio.wait_for(pod.inference.asked.wait(), 5)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    resumed = [e.text for e in world.second.inference.prompts[0].messages if isinstance(e, Message)]
    assert resumed[-2:] == [DONE.text, SAID]
    assert world.hers() == [ANOTHER.text]


def test_another_persons_message_while_a_tool_runs_is_handed_to_the_running_turn_by_their_own_name(
        world: World) -> None:
    other = Person(person(world.url, world.who.household_id, "Elodie"), world.who.household_id, "Elodie")
    services.register(People, OnePerson(Household(world.who.household_id, "home", "America/Denver", "",
                                                  (world.who, other))))
    tools = Sends()
    pod = Pod(Hooked(), tools)
    world.first = pod
    pod.inference.script = [switch_on(), DONE]

    async def second() -> None:
        assert (await respond(replace(bench_turn(world, SECOND), speaker_id=other.id))).follows

    tools.during = second

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            assert (await respond(bench_turn(world))).body == DONE.text

    run(go())
    handed = [e.text for e in pod.inference.prompts[1].messages if isinstance(e, Message)]
    assert handed[-1] == f"Elodie just said: {SECOND}"
    assert world.hers() == [DONE.text]


def test_several_messages_while_a_tool_runs_are_handed_together_in_the_order_they_were_said(world: World) -> None:
    tools = Sends()
    pod = Pod(Hooked(), tools)
    world.first = pod
    pod.inference.script = [switch_on(), DONE]
    said = [SECOND, "and the hall", "no, just the porch"]

    async def several() -> None:
        for text in said:
            assert (await respond(bench_turn(world, text))).follows

    tools.during = several

    async def go() -> None:
        async with database(world):
            world.as_pod(pod)
            assert (await respond(bench_turn(world))).body == DONE.text

    run(go())
    handed = [e.text for e in pod.inference.prompts[1].messages if isinstance(e, Message)]
    assert handed[-3:] == [f"Alana just said: {t}" for t in said]
    assert world.hers() == [DONE.text]
