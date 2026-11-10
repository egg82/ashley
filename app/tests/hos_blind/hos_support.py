"""Pieces of the her-own-setup blind tests: the tokens and tunables, logs, two households with people on a real database,
the real `PostgresConnections`, and an object store double written against the `ObjectStore` interface."""

import asyncio
import hashlib
import io
import logging
import os
import zipfile
from collections.abc import AsyncGenerator, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import psycopg
import pytest
from ashley.codehost.config import CodeHostConfig
from ashley.codehost.model import Access, Forge
from ashley.connections.connections import Connections
from ashley.connections.model import Kind
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.pool import PoolDatabase
from ashley.files.store import ObjectStore, StoreUnavailable
from ashley.people import admin
from connection_legacy_support import put_of


T = TypeVar("T")

GITLAB = "https://gitlab.test"
GITHUB_API = "https://api.github.com"
GITHUB = "github.com"
CODELOAD = "codeload.github.com"
SMALL = CodeHostConfig(timeout_s=5.0, projects_max=5, tree_max=5, read_bytes=64, snapshot_max_bytes=2000)
RESULT_CHARS = 300

GL_ALANA, GL_SAM, GL_KIM = "glpat-alana-0001-SECRET", "glpat-sam-0002-SECRET", "glpat-kim-0003-SECRET"  # gitleaks:allow (test fixture)
GH_ALANA, GH_SAM, GH_KIM = "github_pat_alana_0001_SECRET", "github_pat_sam_0002_SECRET", "github_pat_kim_0003_SECRET"
ALL_TOKENS = (GL_ALANA, GL_SAM, GL_KIM, GH_ALANA, GH_SAM, GH_KIM)


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def zip_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


# --- logs ---------------------------------------------------------------------------------------------------------


def log_text(caplog: pytest.LogCaptureFixture, only: str = "") -> str:
    """Every captured record (of loggers starting with `only`) as its message, its structured fields and any
    exception text."""
    out: list[str] = []
    for r in caplog.records:
        if only and not r.name.startswith(only):
            continue
        out.append(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''} {r.exc_info!r}")
    return "\n".join(out)


def fields_of(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def all_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)


# --- people and connections ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    url: str
    home: int
    alana: int
    sam: int
    lee: int
    other: int
    kim: int


def world(url: str) -> World:
    with psycopg.connect(url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, lee = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, home, "Lee"))
        kim = admin.add_person(conn, other, "Kim")
    return World(url, home, alana, sam, lee, other, kim)


KEY = os.urandom(32)


def sealer(key: bytes = KEY) -> Sealer:
    return Sealer({1: key}, current=1)


@asynccontextmanager
async def connections(url: str, key: bytes = KEY) -> AsyncGenerator[Connections]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresConnections(database, sealer(key))
    finally:
        await database.close()


async def connect(c: Connections, person: int, household: int, kind: Kind, token: str, base: str = "") -> None:
    """Add `person`'s own connection of `kind` (a code host) as the app would store it."""
    default = GITLAB if kind == "gitlab" else GITHUB_API
    await put_of(c, household, kind, base or default, token, person)


def access_for(forge: Forge, token: str) -> Access:
    return Access(forge, GITLAB if forge == "gitlab" else GITHUB_API, token)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- an object store ----------------------------------------------------------------------------------------------


class FakeStore(ObjectStore):
    def __init__(self) -> None:
        self.held: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> int:
        self.held[key] = data
        return 1

    async def get(self, key: str) -> bytes | None:
        return self.held.get(key)

    async def keys(self, prefix: str) -> frozenset[str]:
        return frozenset(k for k in self.held if k.startswith(prefix))

    async def delete(self, key: str) -> None:
        self.held.pop(key, None)

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        return {k: datetime.now(UTC) for k in self.held if k.startswith(prefix)}


class DownStore(FakeStore):
    async def put(self, key: str, data: bytes) -> int:
        raise StoreUnavailable("down")
