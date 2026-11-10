"""Shared pieces of the skills blind contract tests: two households (Alana and Sam share `home`, Zed is alone in
`next_door`), the Postgres Skills service built from its public constructor with seeds of the test's choosing, the real
Workshop beside it for the bench tools, and the routes through the real app."""

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import count
from typing import Any

import pytest
from contract.conversations_support import household, person
from fastapi.testclient import TestClient
from httpx2 import Response
from live_support import FakeLive
from respond_support import Fakes

from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.skills import config as skills_config
from ashley.skills.config import SkillsConfig
from ashley.skills.postgres import PostgresSkills
from ashley.skills.seeds import Seed
from ashley.skills.skills import Edited, Skill, SkillRefused, Skills
from ashley.tools.bench_skills import BenchSkillTools
from ashley.tools.tools import Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop

PUBLIC = "https://ashley.test"
CONFIG: SkillsConfig = skills_config.load()
CODE = Seed("code", "Code", "agentic-engineering", "SEED-CODE-BODY")
SEEDS: Mapping[str, Seed] = {"code": CODE}
_ids = count(1)


@dataclass(frozen=True)
class World:
    url: str
    alana: Owner
    sam: Owner
    zed: Owner


def world(url: str) -> World:
    h1, h2 = household(url, "home"), household(url, "next door")
    return World(url, Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


@asynccontextmanager
async def skills(url: str, seeds: Mapping[str, Seed] = SEEDS, config: SkillsConfig = CONFIG) -> AsyncGenerator[Skills]:
    db = PoolDatabase(url)
    await db.open()
    try:
        yield PostgresSkills(db, config, seeds)
    finally:
        await db.close()


@asynccontextmanager
async def tools_env(url: str, seeds: Mapping[str, Seed] = SEEDS) -> AsyncGenerator[tuple[Skills, Workshop]]:
    """The real Skills and Workshop in the locator, as a turn's bench tools find them."""
    db = PoolDatabase(url)
    await db.open()
    s, w = PostgresSkills(db, CONFIG, seeds), PostgresWorkshop(db, workshop_rules.load())
    services.register(Skills, s)
    services.register(Workshop, w)
    try:
        yield s, w
    finally:
        services.unregister(Skills)
        services.unregister(Workshop)
        await db.close()


async def started(s: Skills, owner: Owner, kind: str = "garden", label: str = "Garden") -> str:
    await s.add_kind(owner.household_id, kind, label)
    return kind


async def put(s: Skills, owner: Owner, kind: str, body: str, base: int, bench_id: int | None = None,
              by: int | None = None, what: str = "w", why: str = "y") -> Edited:
    """An edit; by default hers (no person)."""
    return await s.edit(owner.household_id, kind, body, what, why, base, bench_id, by)


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(f"call-{next(_ids)}", name, arguments)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    """The `fields` of each logged line named `event`."""
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.msg == event]


def everything_logged(caplog: pytest.LogCaptureFixture) -> str:
    return " ".join(f"{r.getMessage()} {getattr(r, 'fields', {})}" for r in caplog.records)


def at_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)


@dataclass
class Rig:
    client: TestClient
    w: World
    who: list[str]

    def as_(self, name: str) -> None:
        self.who[0] = name

    def get(self, path: str) -> Response:
        return self.client.get(path)

    def put(self, path: str, body: object) -> Response:
        return self.client.put(path, json=body)

    def post(self, path: str, body: object = None) -> Response:
        return self.client.post(path, json=body)


def person_of(w: World, name: str) -> Person:
    owner = {"alana": w.alana, "sam": w.sam, "zed": w.zed}[name]
    return Person(owner.person_id, owner.household_id, name.capitalize())


def build(url: str, fakes: Fakes, signed_in: bool = True) -> Rig:
    w = world(url)
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC))
    rig = Rig(TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}), w, ["alana"])
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, person_of(w, rig.who[0]))
    services.register(Live, FakeLive())
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Inference, fakes.inference)
    services.register(Tools, fakes.tools)
    return rig




async def reason_of(call: Awaitable[Any]) -> str:
    """The reason a call was refused with; fails if it was not refused."""
    try:
        await call
    except SkillRefused as e:
        return e.reason
    raise AssertionError("not refused")


async def now(s: Skills, household_id: int, kind: str) -> Skill:
    got = await s.current(household_id, kind)
    assert got is not None
    return got


def tools_of(owner: Owner, bench_id: int) -> BenchSkillTools:
    return BenchSkillTools(owner.household_id, owner.person_id, bench_id)


def data(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loaded: dict[str, Any] = json.loads(result.content)
    return loaded


async def bench_with(workshop: Workshop, owner: Owner, work: str | None = None) -> int:
    bench = (await workshop.open(owner, "b")).id
    if work is not None:
        await workshop.set_work(owner, bench, work)
    return bench


async def instructions(t: BenchSkillTools) -> str:
    return (await t.catalogue()).instructions or ""


def edit(**over: object) -> Any:
    args: dict[str, object] = {"body": "NEW", "base_version": 0, "what": "w", "why": "y", **over}
    return call("skill_edit", **args)
