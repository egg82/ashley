"""A device, its legacy `device_controls` rows and a Workshop on a real database, for the screen-bench suites."""

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.live import Live
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Rules
from contract.conversations_support import household, person, scalar
from live_support import FakeLive

LIGHT = ("bedroom-off", "Bedroom off", "light.turn_off", "light.zq_bedroom")
SCENE = ("nightlight", "Nightlight", "scene.turn_on", "scene.zq_night")


def device(url: str, household_id: int, name: str = "hall tablet") -> int:
    return int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                           "VALUES (%s, %s, 'hallway', 'present', 'text', 'chat', sha256(%s::bytea)) RETURNING id",
                      (household_id, name, secrets.token_bytes(8))))


def legacy_controls(url: str, household_id: int, device_id: int, *rows: tuple[str, str, str, str]) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for position, (name, label, action, entity) in enumerate(rows):
            conn.execute("INSERT INTO device_controls (device_id, household_id, name, position, label, action, entity_id) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s)", (device_id, household_id, name, position, label, action, entity))


def count(url: str, query: str, *params: object) -> int:
    return int(scalar(url, query, params))


@asynccontextmanager
async def shop(url: str, screen_rules: Rules | None = None) -> AsyncGenerator[tuple[PostgresWorkshop, FakeLive]]:
    live = FakeLive()
    services.register(Live, live)
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresWorkshop(database, workshop_rules.load(), screen_rules), live
    finally:
        await database.close()


__all__ = ["LIGHT", "SCENE", "count", "device", "household", "legacy_controls", "person", "shop"]
