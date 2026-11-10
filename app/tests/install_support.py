"""A world for installing a bench's automation pieces over a real database: the Postgres Workshop and Installs on one
pool, a fake Home Assistant (`automations_support.FakeHouse`) as the house's automations, and a Live that keeps what it
heard; and the commands that put a proposed automation piece on a bench."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.homes import Homes
from ashley.live.live import Live
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Install, Propose
from ashley.workshop.install_piece import automation_id_for
from ashley.workshop.installs import Installs
from ashley.workshop.installs_postgres import PostgresInstalls
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from automations_support import FakeHouse
from homes_support import AnyHousehold
from bench_run_support import Heard

RULES = workshop_rules.load()
CONFIG: dict[str, Any] = {
    "alias": "ashley bench test, delete me", "description": "",
    "triggers": [{"trigger": "time", "at": "03:33:00"}],
    "conditions": [{"condition": "state", "entity_id": "light.porch", "state": "nonexistent"}],
    "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}], "mode": "single"}


def body(**changes: object) -> str:
    return json.dumps({**CONFIG, **changes})


def add(owner: Owner, text: str | None = None) -> Add:
    return Add(By(owner.person_id), "automation", Text("porch", body() if text is None else text), "medium")


def propose(piece: int = 1, version: int = 1, enabled: bool = False, turn_off: str | None = None) -> Propose:
    return Propose(HER, piece, version, enabled, turn_off)


def install(owner: Owner, bench_id: int, proposal: int, piece: int = 1) -> Install:
    return Install(By(owner.person_id), piece, proposal, automation_id_for(bench_id, piece))


@dataclass
class World:
    house: FakeHouse
    heard: Heard
    database: PoolDatabase


@asynccontextmanager
async def world(url: str, house: FakeHouse | None = None) -> AsyncGenerator[World]:
    database = PoolDatabase(url)
    await database.open()
    made = World(house or FakeHouse(), Heard(), database)
    services.register(Workshop, PostgresWorkshop(database, RULES))
    services.register(Installs, PostgresInstalls(database))
    services.register(Homes, AnyHousehold(made.house.client()))
    services.register(Live, made.heard)
    try:
        yield made
    finally:
        for interface in (Workshop, Installs, Homes, Live):
            services.unregister(interface)
        await database.close()
