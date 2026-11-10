"""A pod lost mid-escalation: another pod resumes the turn on the stronger route, once, and the held line and the answer
are each delivered once."""

import asyncio
from contextlib import suppress

import pytest
from ashley import logs
from ashley.channels import resume
from ashley.channels.respond import respond
from ashley.inference.reply import Reply
from contract.conversations_support import events, run
from escalation_blind_support import (DONE, HANG, THINKING, World, database, escalating, kill_the_turn, rounds)

CHAT_ROUNDS = 6


async def lose_the_first_pod(w: World) -> "asyncio.Task[object]":
    """Start the turn on the first pod, wait for its hanging step, then kill it as a dead pod; the claim runs out."""
    w.as_pod(w.first)
    turn = asyncio.ensure_future(respond(w.inbound()))
    await asyncio.wait_for(w.first.model.asked.wait(), 5)
    assert kill_the_turn() >= 1
    await asyncio.sleep(0.45)
    return turn


async def other_pod_resumes(w: World) -> None:
    w.as_pod(w.second)
    assert await resume.sweep() == 1
    assert await resume.sweep() == 0


def test_a_pod_lost_on_the_stronger_route_after_a_round_limit_is_resumed_there_once(world: World) -> None:
    world.first.model.script = [*rounds(CHAT_ROUNDS), HANG]
    world.second.model.script = [DONE]

    async def go() -> None:
        async with database(world):
            turn = await lose_the_first_pod(world)
            with suppress(asyncio.CancelledError):
                await turn
            await other_pod_resumes(world)

    run(go(), 30)
    assert world.second.model.tasks == ["escalated"] and world.second.tools.ran == []
    assert world.hers() == [(f"Aside {CHAT_ROUNDS}.", True), (DONE.text, False)]
    assert world.work() == 0


def test_a_pod_lost_on_the_stronger_route_after_a_b_reply_is_resumed_there_once(world: World) -> None:
    world.first.model.script = [escalating(), HANG]
    world.second.model.script = [DONE]

    async def go() -> None:
        async with database(world):
            turn = await lose_the_first_pod(world)
            with suppress(asyncio.CancelledError):
                await turn
            await other_pod_resumes(world)

    run(go(), 30)
    assert world.second.model.tasks == ["escalated"]
    assert world.hers() == [(THINKING, True), (DONE.text, False)]


def test_the_resumed_stronger_route_that_sets_escalate_is_not_a_chain(world: World) -> None:
    again = Reply(spoken=DONE.spoken, text=DONE.text, escalate="and again")
    world.first.model.script = [escalating(), HANG]
    world.second.model.script = [again]

    async def go() -> None:
        async with database(world):
            turn = await lose_the_first_pod(world)
            with suppress(asyncio.CancelledError):
                await turn
            await other_pod_resumes(world)

    run(go(), 30)
    assert world.second.model.tasks == ["escalated"]
    assert world.hers() == [(THINKING, True), (DONE.text, False)]


def test_the_escalation_is_logged_once_across_both_pods(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.first.model.script = [*rounds(CHAT_ROUNDS), HANG]
    world.second.model.script = [DONE]

    async def go() -> None:
        async with database(world):
            turn = await lose_the_first_pod(world)
            with suppress(asyncio.CancelledError):
                await turn
            await other_pod_resumes(world)

    logs.setup()
    capsys.readouterr()
    run(go(), 30)
    got = capsys.readouterr()
    assert len(events(got.out + got.err, "respond.escalated")) == 1


def test_a_pod_lost_before_the_turn_escalated_is_resumed_on_the_fast_route_and_escalates_once_at_the_limit(
        world: World) -> None:
    world.first.model.script = [*rounds(3), HANG]
    world.second.model.script = [*rounds(3, start=4), DONE]

    async def go() -> None:
        async with database(world):
            turn = await lose_the_first_pod(world)
            with suppress(asyncio.CancelledError):
                await turn
            await other_pod_resumes(world)

    run(go(), 30)
    tasks = world.second.model.tasks
    assert tasks[0] == "chat" and tasks.count("escalated") == 1 and tasks[-1] == "escalated"
    assert world.hers()[-1] == (DONE.text, False) and [t for t, _ in world.hers()].count(DONE.text) == 1
