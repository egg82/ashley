"""A chat turn through `respond` on web chat (a channel that takes a later reply), over Postgres: the held line goes out
once as her turn marked `follows`, the stronger route's answer is stored later as a separate turn, once; a turn answered
in time, or of a kind that does not escalate, never asks the stronger route; logs carry ids and counts only."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels.model import Medium, Outbound
from ashley.channels.respond import respond
from ashley.inference.model import Task
from ashley.inference.reply import Reply
from contract.conversations_support import run
from escalation_blind_support import (CHECKING, DONE, THINKING, World, database, done, escalating, rounds, settled,
                                      switch_on)

CHAT_ROUNDS = 6
COMMAND_ROUNDS = 4
BRAINSTORM_ROUNDS = 24


def a_turn(w: World, *, text: str = "turn on the lamps", settle_to: int = 2) -> Outbound:
    async def go() -> Outbound:
        async with database(w):
            w.as_pod(w.first)
            out = await respond(w.inbound(text))
            await settled(w, settle_to)
            await asyncio.sleep(0.15)
            return out

    return done(go())


def test_a_turn_answered_in_time_never_asks_the_stronger_route(world: World) -> None:
    world.first.model.script = [switch_on(1), DONE]
    out = a_turn(world, settle_to=1)
    assert not out.follows
    assert world.first.model.tasks == ["chat", "chat"]
    assert world.hers() == [(DONE.text, False)]


def test_a_turn_at_its_round_limit_says_its_latest_aside_then_answers_later_from_the_stronger_route(world: World) -> None:
    world.first.model.script = [*rounds(CHAT_ROUNDS), DONE]
    out = a_turn(world)
    assert (out.follows, out.body) == (True, f"Aside {CHAT_ROUNDS}.")
    assert world.first.model.tasks == ["chat"] * CHAT_ROUNDS + ["escalated"]
    assert world.hers() == [(f"Aside {CHAT_ROUNDS}.", True), (DONE.text, False)]
    assert len(world.first.tools.ran) == CHAT_ROUNDS and world.work() == 0


def test_a_reply_that_sets_escalate_says_that_line_then_answers_later_from_the_stronger_route(world: World) -> None:
    world.first.model.script = [escalating(), DONE]
    out = a_turn(world)
    assert (out.follows, out.body) == (True, THINKING)
    assert world.first.model.tasks == ["chat", "escalated"]
    assert world.hers() == [(THINKING, True), (DONE.text, False)]


def test_the_stronger_route_goes_on_from_what_the_fast_one_found(world: World) -> None:
    world.first.model.script = [*rounds(2), escalating(), DONE]
    a_turn(world)
    assert world.first.model.tasks == ["chat"] * 3 + ["escalated"]
    assert len(world.first.model.seen[3].messages) > len(world.first.model.seen[0].messages)
    assert len(world.first.tools.ran) == 2


def test_a_person_who_has_had_a_held_line_gets_no_second_one_when_the_turn_escalates(world: World) -> None:
    world.first.model.script = [CHECKING, escalating(), DONE]
    out = a_turn(world)
    assert (out.follows, out.body) == (True, CHECKING.text)
    assert world.first.model.tasks == ["chat", "chat", "escalated"]
    assert world.hers() == [(CHECKING.text, True), (DONE.text, False)]


def test_the_stronger_route_hitting_its_own_limit_wraps_up_and_answers_never_escalating_again(world: World) -> None:
    left = BRAINSTORM_ROUNDS - CHAT_ROUNDS
    world.first.model.script = [*rounds(CHAT_ROUNDS), *rounds(left, start=CHAT_ROUNDS + 1), DONE]
    a_turn(world)
    model = world.first.model
    assert model.tasks.count("chat") == CHAT_ROUNDS and model.tasks.count("escalated") == left + 1
    assert model.choices("escalated")[-1] == "none" and set(model.choices("escalated")[:-1]) == {"auto"}
    assert world.hers() == [(f"Aside {CHAT_ROUNDS}.", True), (DONE.text, False)]


def test_a_stronger_route_reply_that_sets_escalate_again_is_its_answer_and_stores_once(world: World) -> None:
    again = Reply(spoken=DONE.spoken, text=DONE.text, escalate="and once more")
    world.first.model.script = [escalating(), again]
    a_turn(world)
    assert world.first.model.tasks == ["chat", "escalated"]
    assert world.hers() == [(THINKING, True), (DONE.text, False)]


MEDIA: list[Medium] = ["text", "spoken"]


@pytest.mark.parametrize("medium", MEDIA)
def test_a_command_turn_at_its_round_limit_closes_on_its_own_route_and_never_escalates(world: World, medium: Medium) -> None:
    world.first.model.script = [*rounds(COMMAND_ROUNDS), DONE]
    inbound = replace(world.inbound(kind="command"), medium=medium)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(inbound)
            await asyncio.sleep(0.3)

    run(go(), 30)
    assert world.first.model.tasks == ["command"] * (COMMAND_ROUNDS + 1)
    assert world.first.model.choices("command")[-1] == "none"
    assert world.hers() == [(DONE.text, False)]


def test_a_command_turn_whose_reply_sets_escalate_never_asks_the_stronger_route(world: World) -> None:
    world.first.model.script = [escalating(), DONE, DONE]
    inbound = world.inbound(kind="command")

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(inbound)
            await asyncio.sleep(0.3)

    run(go(), 30)
    tasks: list[Task] = world.first.model.tasks
    assert "escalated" not in tasks and tasks[0] == "command"
