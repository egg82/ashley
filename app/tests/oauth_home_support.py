"""A household of two people, signed in by cookie, against the real app, a real database and the fake Google
(`oauth_google_support`), for the OAuth connect and renewal tests."""

import base64
import hashlib
import os
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.connections.oauth import OAuthProviders
from ashley.mail.mailbox import Mailbox
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from fastapi.testclient import TestClient
from oauth_google_support import FakeGoogle

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
KEY = base64.b64encode(os.urandom(32)).decode()
CALLBACK = "/api/connections/oauth/google/callback"


@dataclass(frozen=True)
class Home:
    household: int
    alana: int
    sam: int
    alana_token: str
    sam_token: str


def _session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    token = secrets.token_urlsafe(16)
    account = admin.add_account(conn, person, "authentik", sub)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


@pytest.fixture
def home(db_url: str) -> Home:
    with psycopg.connect(db_url) as conn:
        hid = admin.add_household(conn, "home", "America/Denver")
        alana, sam = admin.add_person(conn, hid, "Alana"), admin.add_person(conn, hid, "Sam")
        return Home(hid, alana, sam, _session(conn, alana, hid, "sub-alana"), _session(conn, sam, hid, "sub-sam"))


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def client(db_url: str, home: Home, google: FakeGoogle) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=KEY))
    services.register(OAuthProviders, OAuthProviders({"google": google.provider()}))
    services.register(Mailbox, Mailbox.null())   # no test here reaches a mail service unless it registers its own
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        as_(c, home.alana_token)
        yield c
    services.unregister(OAuthProviders)
    services.unregister(Mailbox)


def as_(client: TestClient, token: str) -> None:
    client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")


def start(client: TestClient, google: FakeGoogle, label: str = "", **body: Any) -> tuple[str, str]:
    """(code, state) the browser would carry back from Google, after a start that answered 201."""
    started = client.post("/api/connections/oauth/google/start", json={"kind": "google", "label": label, **body},
                          headers=ORIGIN)
    assert started.status_code == 201, started.text
    return google.authorize(started.json()["authorize_url"])


def back(client: TestClient, **query: str) -> str:
    done = client.get(CALLBACK, params=query)
    assert done.status_code == 302
    return done.headers["location"]


def connect(client: TestClient, google: FakeGoogle, label: str = "") -> str:
    code, state = start(client, google, label)
    return back(client, code=code, state=state)
