"""The real app on a real database, signed in as a person of one household, for the NUL-in-free-text contract: any
`str` a request carries is refused with a 422 when it holds a NUL, as it would a field out of its limits, and never
reaches a text column."""

import base64
import hashlib
import os
import secrets
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
NUL = "\x00"
NUL_PATH = "%00"
APP_KEY = base64.b64encode(os.urandom(32)).decode()


def person_in(db_url: str) -> str:
    """Alana of a household, with a live session; its token."""
    with psycopg.connect(db_url) as conn:
        home = admin.add_household(conn, "home", "America/Denver")
        alana = admin.add_person(conn, home, "Alana")
        account = admin.add_account(conn, alana, "oidc", "a")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
    return token


@contextmanager
def app_client(db_url: str, token: str) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as client:
        client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
        yield client
