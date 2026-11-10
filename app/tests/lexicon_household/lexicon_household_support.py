"""Support for the household-lexicon suite: two households of people signed in over the app on a real database."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import base64
import socket
import hashlib
import os
import secrets
from dataclasses import dataclass

import psycopg
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from fastapi.testclient import TestClient
from ashley.channels.lexicons import Lexicons
from ashley.channels.postgres_lexicons import PostgresLexicons
from ashley.db.pool import PoolDatabase
from httpx2 import Response

BASE = "/api/lexicon"
PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}


@dataclass(frozen=True)
class People:
    alana: int
    sam: int
    kim: int
    home: int
    other: int
    tokens: dict[str, str]


def _session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "oidc", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def people_in(db_url: str) -> People:
    """Alana and Sam of one household, Kim of another, each with a signed-in session."""
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return People(alana, sam, kim, home, other, {"alana": _session(conn, alana, home, "a"),
                                                    "sam": _session(conn, sam, home, "s"),
                                                    "kim": _session(conn, kim, other, "k")})


def app_client(db_url: str) -> TestClient:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC,
                              connections_key=base64.b64encode(os.urandom(32)).decode()))
    return TestClient(app, base_url=PUBLIC, follow_redirects=False)


def as_(client: TestClient, people: People, who: str | None) -> None:
    client.cookies.clear()
    if who is not None:
        client.cookies.set(SESSION_COOKIE, people.tokens[who], domain="ashley.test")


def put(client: TestClient, real: str, spoken: str) -> Response:
    return client.put(f"{BASE}/{real}", json={"spoken": spoken}, headers=ORIGIN)


def delete(client: TestClient, real: str) -> Response:
    return client.delete(f"{BASE}/{real}", headers=ORIGIN)


def listed(client: TestClient) -> dict[str, str]:
    got = client.get(BASE)
    assert got.status_code == 200, got.text
    return {w["real"]: w["spoken"] for w in got.json()["words"]}


def unreachable() -> str:
    """A connection string to a local port nothing listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"host=127.0.0.1 port={port} dbname=ashley user=postgres password=pw connect_timeout=3"


def count_in(db_url: str, household: int) -> int:
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT count(*) FROM household_lexicon WHERE household_id = %s", (household,)).fetchone()
    assert row is not None
    return int(row[0])


@asynccontextmanager
async def lexicons(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[Lexicons]:
    """`PostgresLexicons` over the database, as the app builds it."""
    database = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await database.open()
    try:
        yield PostgresLexicons(database)
    finally:
        await database.close()
