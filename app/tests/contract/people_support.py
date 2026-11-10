"""Helpers for the blind People and Devices tests: rows seeded with raw SQL against the 0004 schema, and the Postgres
implementations built over a pool. Those implementations are imported inside the builders, so this suite still
collects before they exist (`ashley.people.postgres.PostgresPeople`, `ashley.channels.postgres_devices.
PostgresDevices`, each assumed to take the `Database` as its one argument)."""

import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

import psycopg
from ashley.channels.devices import Devices
from ashley.db.pool import PoolDatabase
from ashley.people.people import People
from conversations_support import scalar


def execute(url: str, query: str, params: tuple[object, ...] = ()) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(query.encode(), params)


def home(url: str, name: str = "home", timezone: str = "America/Denver", profile: str = "") -> int:
    return int(scalar(url, "INSERT INTO households (name, timezone, profile) VALUES (%s, %s, %s) RETURNING id",
                      (name, timezone, profile)))


def account(url: str, household_id: int, person_id: int, system: str, external_id: str) -> int:
    return int(scalar(url, "INSERT INTO accounts (household_id, person_id, system, external_id) "
                           "VALUES (%s, %s, %s, %s) RETURNING id", (household_id, person_id, system, external_id)))


def sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def device(url: str, household_id: int, token: str, name: str = "kitchen satellite", place: str = "kitchen",
           audience: str = "present", medium: str = "spoken", kind: str = "command") -> int:
    return int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                      (household_id, name, place, audience, medium, kind, sha256(token))))


def build(module: str, cls: str, database: PoolDatabase) -> Any:
    return getattr(import_module(module), cls)(database)


@asynccontextmanager
async def people(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[People]:
    db = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await db.open()
    try:
        made = build("ashley.people.postgres", "PostgresPeople", db)
        assert isinstance(made, People)
        yield made
    finally:
        await db.close()


@asynccontextmanager
async def devices(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[Devices]:
    db = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await db.open()
    try:
        made = build("ashley.channels.postgres_devices", "PostgresDevices", db)
        assert isinstance(made, Devices)
        yield made
    finally:
        await db.close()
