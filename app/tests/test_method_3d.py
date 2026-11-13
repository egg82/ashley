"""Her 3D method reaches a bench turn whose kind of work is 3d, through `turn_tools.for_turn` and the real skills
catalogue, and no other turn: not web chat, not a bench with another kind or none. What the seed names matches what the
workshop and the sandbox accept."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace

from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.skills import config as skills_config
from ashley.skills import seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.skills import Skills
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.facts import SOURCES, UNITS
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

CONFIG = skills_config.load()
MARK = "# Method for 3D work"


class Everyday(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("look_up", "look_up", {"type": "object"}),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError


@asynccontextmanager
async def wired(url: str) -> AsyncGenerator[Workshop]:
    db = PoolDatabase(url)
    await db.open()
    workshop = PostgresWorkshop(db, workshop_rules.load())
    services.register(Skills, PostgresSkills(db, CONFIG, seeds.load(CONFIG)))
    services.register(Workshop, workshop)
    services.register(Tools, Everyday())
    try:
        yield workshop
    finally:
        services.unregister(Tools)
        services.unregister(Workshop)
        services.unregister(Skills)
        await db.close()


def inbound(owner: Owner, bench: int | None) -> Inbound:
    base = Inbound(household_id=owner.household_id, thread="person:1:web", text="hi", kind="chat", medium="text",
                   audience="owner", speaker_id=owner.person_id, shared=False, place=None, channel="web", later=True,
                   later_by="turn")
    if bench is None:
        return base
    return replace(base, thread=f"bench:{bench}", kind="brainstorm", opens_benches=False, bench_id=bench)


async def instructions(tools: Tools) -> str:
    return (await tools.catalogue()).instructions or ""


def test_the_method_loads_on_a_3d_bench_turn_and_on_no_other(db_url: str) -> None:
    home = household(db_url)
    owner = Owner(home, person(db_url, home, "Alana"))

    async def scenario() -> None:
        async with wired(db_url) as workshop:
            three = (await workshop.open(owner, "case")).id
            await workshop.set_work(owner, three, "3d")
            other = (await workshop.open(owner, "notes")).id
            await workshop.set_work(owner, other, "code")
            bare = (await workshop.open(owner, "bare")).id
            loaded = await instructions(for_turn(inbound(owner, three)))
            assert MARK in loaded and "build123d" in loaded
            for elsewhere in (inbound(owner, other), inbound(owner, bare), inbound(owner, None)):
                assert MARK not in await instructions(for_turn(elsewhere))

    run(scenario())


def test_a_bench_turn_is_told_about_the_model_and_facts_kinds_whatever_its_kind_of_work(db_url: str) -> None:
    home = household(db_url)
    owner = Owner(home, person(db_url, home, "Alana"))

    async def scenario() -> None:
        async with wired(db_url) as workshop:
            bare = (await workshop.open(owner, "bare")).id
            text = await instructions(for_turn(inbound(owner, bare)))
            assert "kind model" in text and "kind facts" in text and "kind of work to 3d" in text
            assert "kind model" not in await instructions(for_turn(inbound(owner, None)))

    run(scenario())


def test_what_the_method_names_is_what_the_workshop_and_sandbox_take() -> None:
    body = seeds.load(CONFIG)["3d"].body
    kinds = workshop_rules.load().kinds
    assert kinds["model"].language == "build123d" and kinds["facts"].format == "facts"
    for word in (*sorted(UNITS), *sorted(SOURCES), "name", "value", "unit", "source", "tolerance", "ref"):
        assert f"`{word}`" in body or f'"{word}"' in body, word
    for name in ("measured", "check", "show", "bench_run", "bench_look", "unconfirmed"):
        assert name in body
