"""Support for the household-page suite: two households of people signed in over the app on a real database."""

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any

import psycopg
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from fastapi.testclient import TestClient
from httpx2 import Response

BASE = "/api/household"
PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
METRIC: dict[str, Any] = {"timezone": "Europe/London", "profile": "Two cats, Mochi and Nuuk.", "locale": "en-GB",
          "unit_system": "metric", "clock": "12h", "latitude": None, "longitude": None}
LOCATED: dict[str, Any] = {**METRIC, "latitude": 51.507222, "longitude": -0.1275}


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
    """Alana and Sam of one household (America/Denver), Kim of another (UTC), each with a signed-in session."""
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


def put(client: TestClient, body: dict[str, Any]) -> Response:
    return client.put(BASE, json=body, headers=ORIGIN)


def stored(db_url: str, household: int) -> tuple[str, str, str, str, str, float | None, float | None]:
    """The household's (timezone, profile, locale, unit_system, clock, latitude, longitude) as the database holds them."""
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT timezone, profile, locale, unit_system, clock, latitude, longitude "
                           "FROM households WHERE id = %s", (household,)).fetchone()
    assert row is not None
    return row[0], row[1], row[2], row[3], row[4], row[5], row[6]
