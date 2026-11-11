"""The household page API (`GET`/`PUT /api/household`) driven through the real app on a real database, signed in as a
person of one of two households. The contract it pins is the wire models in `ashley.api.household_models`, the
`HouseholdWriter` interface and `openapi.json`; nothing here reads the route's implementation."""

import base64
import hashlib
import os
import secrets
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from fastapi.testclient import TestClient
from httpx2 import Response

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
URL = "/api/household"

NEUTRAL_DEFAULTS: dict[str, Any] = {"profile": "", "locale": "en-US", "unit_system": "imperial", "clock": "24h",
                                    "latitude": None, "longitude": None}
FIELDS = ("timezone", "profile", "locale", "unit_system", "clock", "latitude", "longitude")


@dataclass(frozen=True)
class People:
    alana: int
    sam: int
    kim: int
    home: int
    other: int
    tokens: dict[str, str]


def _session(conn: psycopg.Connection, person: int, sub: str, household: int) -> str:
    account = admin.add_account(conn, person, "oidc", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def people_in(db_url: str) -> People:
    """Alana and Sam in `home` (America/Denver), Kim in `other` (UTC); each with a live session."""
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                           admin.add_person(conn, other, "Kim"))
        return People(alana, sam, kim, home, other, {"alana": _session(conn, alana, "a", home),
                                                    "sam": _session(conn, sam, "s", home),
                                                    "kim": _session(conn, kim, "k", other)})


@contextmanager
def app_client(db_url: str) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as client:
        yield client


def as_(client: TestClient, people: People, who: str | None) -> None:
    client.cookies.clear()
    if who is not None:
        client.cookies.set(SESSION_COOKIE, people.tokens[who], domain="ashley.test")


def body(**changes: Any) -> dict[str, Any]:
    """A request every field of which is valid, with `changes` applied."""
    return {"timezone": "Europe/Paris", "profile": "Two adults and a cat.", "locale": "fr-FR", "unit_system": "metric",
            "clock": "12h", "latitude": 48.85, "longitude": 2.35, **changes}


def put(client: TestClient, payload: Mapping[str, Any], headers: Mapping[str, str] = ORIGIN) -> Response:
    return client.put(URL, json=dict(payload), headers=dict(headers))


def get(client: TestClient) -> Response:
    return client.get(URL)


def stored(client: TestClient) -> dict[str, Any]:
    got = get(client)
    assert got.status_code == 200, got.text
    return dict(got.json())


def fields_of(household: Mapping[str, Any]) -> dict[str, Any]:
    return {k: household[k] for k in FIELDS}

