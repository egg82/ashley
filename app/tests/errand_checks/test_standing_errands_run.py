"""A standing errand through the `wakes` runner and the real turn loop, with the real skills: each time its rule comes
round her turn follows the household's skill as its method, may use only the tools it names, and what she finds
reaches the person by its route when she says it, while a round with nothing to tell sends nothing; the next round is
stored with the method on. A method that cannot be read tells her to carry out nothing, and a round killed on one pod
is finished on another with the method read again."""

import asyncio
from collections.abc import AsyncGenerator, Generator, Mapping
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from ashley import services
from ashley.channels import resume
from ashley.channels.wake import runner
from ashley.db.pool import PoolDatabase
from ashley.inference.model import SystemPrompt, ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.persona import persona
from ashley.conversations.model import Kind
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from ashley.skills import config, seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.skills import Skills
from ashley.tools.standing_method import UNREAD
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import CLAIM_S, HANG, World
from rb_support import ZONE, now, stack
from test_errand_checks_run import bring_due, seen

ASK = "PLANTED-STANDING-vw tell me when a two-bedroom near the park is listed"
METHOD = "# Method for this standing errand (skill research"
SEED = "# Method for research work"
FOUND = Reply(spoken="A two-bedroom on Elm is listed.", text="A two-bedroom on Elm is listed.")
QUIET = Reply(spoken="Nothing new.", text="Nothing new.", says="none")
LAMP = ToolCalls((ToolCall("c1", "lamp_on", {}),))


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


def standing(house: int, who: int, method: str = "research") -> Reminder:
    due = now() - timedelta(seconds=1)
    return Reminder(house, who, who, ASK, due, Repeat("daily", 1, due.astimezone(ZONE).replace(tzinfo=None)),
                    tools=("lamp_on",), method=method)


def methods(url: str) -> list[object]:
    return list(scalar(url, "SELECT coalesce(json_agg(method ORDER BY id), '[]') FROM wakes"))


def offered(prompt: object) -> list[str]:
    return [t.name for t in getattr(prompt, "tools")]


def test_a_round_follows_its_method_uses_its_tool_and_tells_what_it_found_and_a_quiet_round_sends_nothing(
        instructed: World) -> None:
    world = instructed
    world.first.inference.script = [LAMP, FOUND, QUIET]

    async def go() -> None:
        async with skilled(world.url), stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            assert await runner.sweep() == 1
            assert await s.pushes() == [f"push:{s.alana}"]
            assert methods(world.url) == ["research", "research"] and s.unsettled() == 1
            assert await runner.sweep() == 0   # the next round waits for its rule
            bring_due(world.url)
            assert await runner.sweep() == 1
            assert await s.pushes() == [f"push:{s.alana}"]   # nothing new, nothing sent

    run(go())
    first, _, second = world.first.inference.prompts
    assert [c.name for c in world.first.tools.ran] == ["lamp_on"]
    for prompt in (first, second):
        assert ASK in seen(prompt) and METHOD in seen(prompt) and SEED in seen(prompt)
        assert offered(prompt) == ["lamp_on"]


def test_a_method_that_cannot_be_read_tells_her_to_carry_out_nothing(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [QUIET]

    async def go() -> None:
        async with stack(world) as s:   # no skills wired
            await s.wakes.schedule(standing(s.house, s.alana))
            assert await runner.sweep() == 1
            assert await s.pushes() == []

    run(go())
    (prompt,) = world.first.inference.prompts
    assert UNREAD in seen(prompt) and SEED not in seen(prompt)


def test_a_round_killed_on_one_pod_is_finished_on_another_with_its_method(instructed: World) -> None:
    world = instructed
    world.first.inference.script = [HANG]
    world.second.inference.script = [FOUND]

    async def go() -> None:
        async with skilled(world.url), stack(world) as s:
            await s.wakes.schedule(standing(s.house, s.alana))
            world.as_pod(world.first)
            task = asyncio.create_task(runner.sweep())
            await asyncio.wait_for(world.first.inference.asked.wait(), 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            await runner.sweep()
            await resume.sweep()
            assert methods(world.url) == ["research", "research"] and s.unsettled() == 1
            assert await s.pushes() == [f"push:{s.alana}"]

    run(go())
    (prompt,) = world.second.inference.prompts
    assert ASK in seen(prompt) and METHOD in seen(prompt)
