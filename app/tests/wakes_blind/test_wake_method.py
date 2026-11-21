"""A house wake whose rule names a `method` is a round of a standing errand: the household's skill loads as the turn's
method, only the rule's tools are offered, its answer goes to the phone, and a wake handed in twice, or killed on one
pod and taken up on another, is one round."""

import json
from collections.abc import AsyncGenerator, Generator, Mapping
from contextlib import asynccontextmanager

import pytest
from ashley import services
from ashley.conversations.model import Kind
from ashley.db.pool import PoolDatabase
from ashley.inference.model import SystemPrompt
from ashley.persona import persona
from ashley.skills import config, seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.skills import Skills
from ashley.tools.standing_method import UNREAD
from ashley.workshop.wake_rule import WakeRule, rule_of
from contract.conversations_support import run
from contract.test_inflight_resume import World
from wb_runner_support import DONE, GREET, SILENT, Stack, ran, seen_by_model, stack, sweep

METHOD = "# Method for this standing errand (skill research"
SEED = "# Method for research work"


def body(**changes: object) -> str:
    return json.dumps({"event": "arrived", "brief": "Do a round.", "tools": [], **changes})


@pytest.fixture(autouse=True)
def skills_unwired() -> Generator[None]:
    services.unregister(Skills)
    yield
    services.unregister(Skills)


@pytest.fixture
def instructed(world: World, monkeypatch: pytest.MonkeyPatch) -> World:
    """The world, its stand-in system prompt carrying the tools' instructions, where a method loads."""
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}\n{context.tool_instructions or ''}")}

    monkeypatch.setattr(persona, "system", built)
    return world


@asynccontextmanager
async def skilled(url: str) -> AsyncGenerator[None]:
    """The real skills on the world's database, whose seeds give every household a `research` method."""
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    loaded = config.load()
    services.register(Skills, PostgresSkills(db, loaded, seeds.load(loaded)))
    try:
        yield
    finally:
        await db.close()


def test_a_method_is_read_back_as_written() -> None:
    got = rule_of(body(method="research"))
    assert got == WakeRule("arrived", "Do a round.", (), method="research")
    plain = rule_of(body())
    assert plain == WakeRule("arrived", "Do a round.", ()) and plain is not None and plain.method is None


BAD = {"null": body(method=None), "empty": body(method=""), "not a slug": body(method="Research Work"),
       "a number": body(method=3), "a list": body(method=["research"]), "too long": body(method="a" * 200),
       "greets": body(method="research", greets=True), "a speaker": body(method="research", speaker="media_player.den"),
       "a device": body(method="research", device=4)}


@pytest.mark.parametrize("name", BAD)
def test_a_method_that_is_not_a_slug_or_that_leaves_the_phone_is_no_rule(name: str) -> None:
    assert rule_of(BAD[name]) is None


async def _round(s: Stack, event_id: str = "ctx-1") -> int:
    await s.rule(body=body(method="research", tools=["lamp_on"]))
    return await s.hand_in(event_id)


def test_a_wake_with_a_method_is_a_round_that_follows_the_skill_with_only_its_tool(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with skilled(world.url), stack(world) as s:
            id_ = await _round(s)
            assert await sweep() == 1
            assert s.outcome(id_) == "turn" and s.turns_of(id_) == 1

    run(go())
    (prompt,) = world.first.inference.prompts
    shown = seen_by_model(prompt)
    assert METHOD in shown and SEED in shown and "Do a round." in shown
    assert [t.name for t in prompt.tools] == ["lamp_on"]
    assert world.hers() == [DONE.text]


def test_a_round_with_nothing_to_tell_sends_nothing(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [SILENT]

    async def go() -> None:
        async with skilled(world.url), stack(world) as s:
            await _round(s)
            await sweep()
            assert s.queued() == 0

    run(go())
    assert DONE.text not in world.hers()


def test_a_wake_handed_in_twice_is_one_round(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [DONE, DONE]

    async def go() -> None:
        async with skilled(world.url), stack(world) as s:
            first = await _round(s)
            assert await s.hand_in("ctx-1") == first
            await sweep()
            await sweep()
            assert s.turns_of(first) == 1

    run(go())
    assert len(world.first.inference.prompts) == 1


def test_a_method_that_cannot_be_read_tells_her_to_carry_out_nothing(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [SILENT]

    async def go() -> None:
        async with stack(world) as s:   # no skills wired
            await _round(s)
            await sweep()

    run(go())
    (prompt,) = world.first.inference.prompts
    assert UNREAD in seen_by_model(prompt) and SEED not in seen_by_model(prompt)


def test_a_rule_without_a_method_is_an_ordinary_wake_with_no_method_loaded(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [DONE]

    async def go() -> None:
        async with skilled(world.url), stack(world) as s:
            await s.rule()
            await s.hand_in()
            await sweep()
            assert ran(world.first) == []

    run(go())
    (prompt,) = world.first.inference.prompts
    assert METHOD not in seen_by_model(prompt) and GREET in seen_by_model(prompt)
