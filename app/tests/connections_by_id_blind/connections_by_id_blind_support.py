"""Pieces of the connections-by-id blind tests: test kinds with a chosen `most`, two households with people and
sessions on a real database, the real Postgres Connections for service tests, and the real app with those kinds
registered (and nothing else) for the routes."""

import asyncio
import base64
import hashlib
import os
import secrets
from collections.abc import AsyncGenerator, Coroutine, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

import psycopg
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.codehost.host import CodeHost
from ashley.connections.connections import Connections
from ashley.connections.kinds import Check, ConnectionKind, ConnectionKinds, Refusal
from ashley.connections.model import Port
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.homes import Homes
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.sure.client import Sure
from fastapi.testclient import TestClient

T = TypeVar("T")

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
KEY = os.urandom(32)
SERVICES = (Connections, ConnectionKinds, Sure, Homes, CodeHost)
URL = "https://music.test"
REASONS: tuple[Refusal, ...] = ("bad_url", "key_refused", "unreachable", "wrong_service")


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


@dataclass
class Checks:
    """The `check` a test kind is declared with: records what it was given, answers with what it is set to."""

    given: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    answer: Refusal | None = None

    async def __call__(self, base_url: str, secret: str, person_id: int) -> Refusal | None:
        self.given.append((base_url, secret))
        return self.answer


def kind(name: str, most: int, check: Check, personal: bool = False,
         ports: frozenset[Port] = frozenset()) -> ConnectionKind:
    return ConnectionKind(name=name, title=name.title(), what="music", blurb="blurb", connected="Now connected.",
                          removed="Now removed.", holders=frozenset({"person"} if personal else {"household"}), schemes=frozenset({"https"}),
                          address_placeholder="https://music.example", secret_field="token", secret_label="Token",
                          secret_noun="token", check=check, refusals={r: f"{name} says {r}" for r in REASONS},
                          ports=ports, most=most)


def kinds_for(check: Check) -> tuple[ConnectionKind, ...]:
    """`multi` holds three per household, `solo` one, `big` six, `own` three per person; registered in this order."""
    return (kind("multi", 3, check), kind("solo", 1, check), kind("big", 6, check),
            kind("own", 3, check, personal=True), kind("single_own", 1, check, personal=True))


# --- people ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class People:
    url: str
    home: int
    other: int
    alana: int
    sam: int
    kim: int
    tokens: dict[str, str]


def _session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "oidc", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def make_people(url: str) -> People:
    with psycopg.connect(url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return People(url, home, other, alana, sam, kim, {"alana": _session(conn, alana, home, "a"),
                                                         "sam": _session(conn, sam, home, "s"),
                                                         "kim": _session(conn, kim, other, "k")})


def as_(client: TestClient, people: People, who: str) -> None:
    client.cookies.set(SESSION_COOKIE, people.tokens[who], domain="ashley.test")


def app_client(url: str, checks: Checks, key: str = APP_KEY) -> Generator[TestClient]:
    """The real app on the database, with only the test kinds registered once it has started."""
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=key))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(ConnectionKinds, ConnectionKinds(kinds_for(checks)))
        yield c


# --- the database -----------------------------------------------------------------------------------------------------


def one(url: str, query: str, params: tuple[object, ...] = ()) -> Any:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(query.encode(), params).fetchone()
    assert row is not None
    return row[0]


def rows(url: str) -> int:
    return int(one(url, "SELECT count(*) FROM connections"))


def snapshot(url: str) -> list[tuple[Any, ...]]:
    """Every stored column of every connection, so 'nothing was written' is a comparison."""
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute("SELECT id, household_id, kind, person_id, label, base_url, secret, added_by, added_at, "
                            "checked_at FROM connections ORDER BY id").fetchall()


def age(url: str, connection_id: int) -> tuple[Any, Any]:
    """Move a stored connection's `added_at` and `checked_at` an hour into the past; returns the new pair."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("UPDATE connections SET added_at = added_at - interval '1 hour', "
                           "checked_at = checked_at - interval '1 hour' WHERE id = %s RETURNING added_at, checked_at",
                           (connection_id,)).fetchone()
    assert row is not None
    return row[0], row[1]


# --- Connections without the app -------------------------------------------------------------------------------------


async def _ok(base_url: str, secret: str, person_id: int) -> Refusal | None:
    return None


@asynccontextmanager
async def connections(url: str, kinds: tuple[ConnectionKind, ...] | None = None) -> AsyncGenerator[Connections]:
    """The real Postgres Connections registered with the locator over `kinds` (the test kinds by default)."""
    database = PoolDatabase(url)
    await database.open()
    service = PostgresConnections(database, Sealer({1: KEY}, current=1))
    services.register(ConnectionKinds, ConnectionKinds(kinds if kinds is not None else kinds_for(_ok)))
    services.register(Connections, service)
    try:
        yield service
    finally:
        await database.close()


async def add(c: Connections, household: int, person: int, kind_name: str, label: str = "",
              secret: str = "s3cret-value") -> int:
    return (await c.add(household, kind_name, label, URL, secret, person)).id
