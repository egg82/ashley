"""Blind contract tests for OAuth secrets (decisions.md, "A kind's secret can come from OAuth", build part 1): the real
app on a real database, a fake Google at its HTTP boundary (`mail_oauth_blind_fake_support`), and the people and
sessions the routes need. Everything the design does not name is guessed once, in ASSUMPTIONS below; a test never
guesses on its own.

ASSUMPTIONS (each with the design sentence it rests on; the same list is in assumptions.txt):

A1  Start: `POST /api/connections/oauth/google/start`, same-origin JSON `{"kind": "google", "label": str}`, answers 201
    `{"authorize_url": str}`; 401 signed out, 403 cross-origin, 503 unconfigured. Rests on "a same-origin `POST`
    starts it" and "connecting runs as Discord linking does" (whose start answers 201 `LinkStartResponse`). The
    design names no start path; the callback's `/api/connections/oauth/{provider}/callback` fixes the prefix.
A2  Callback: `GET /api/connections/oauth/google/callback?code=&state=` answers 302 to `/connections?connect=<outcome>`,
    outcome one of `connected`, `cancelled`, `wrong_person`, `failed`, `unavailable`. Rests on "the callback ... the
    one GET that writes" and Discord's `?link=<outcome>` shape.
A3  Settings fields `google_oauth_client_id` and `google_oauth_client_secret` (with `public_url` and
    `connections_key`), and a redirect URI of `<public_url>/api/connections/oauth/google/callback`. Rests on "The
    client's `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`" and Discord's settings.
A4  Provider requests go through `httpx2.AsyncClient` (the repo's one HTTP client), so a patch of its `send` is the
    HTTP boundary; Google's hosts end in `google.com` or `googleapis.com`, the token path ends `/token`, userinfo's
    ends `userinfo`. Rests on "Fake the provider at its HTTP boundary" and the Discord provider's use of httpx2.
A5  The authorization URL asks for `access_type=offline` and the kind's scopes (`openid`, `email`). Rests on "the
    sealed secret is the refresh token" (Google answers one only to an offline request).
A6  `connect_pending` has columns `state_sha256` (bytea, SHA-256 of the state), `person_id` and `created_at`, as
    `link_pending` has. Rests on "keyed by the hash of its state" and "bound to the person who started it".
A7  An access token is obtained with `ashley.connections.oauth.access_token(connection_id, household_id, person_id)`,
    which renews within `refresh_margin_s` and raises `NeedsReconnect` when the connection `needs` a reconnect and
    `OAuthUnavailable` when the provider could not be reached or failed without refusing the grant. A connection that
    person cannot see yields an exception or None, never a token. Rests on "A pod whose access token is within
    `refresh_margin_s` of expiry refreshes" and "her tools over it answer `needs_reconnect`"; the design names
    neither the function nor the exceptions, nor where `refresh_margin_s` lives, so no test pins its value: a token
    expiring in 1 s is within any margin and one expiring in 30 days is outside every sane one.
A8  `Opened.secret` of an OAuth connection is the refresh token. Rests on "the sealed secret is the refresh token".
A9  `GET /api/connections` lists each connection with `needs` (null or `reconnect`), `scopes` (granted) and
    `missing_scopes` (asked for and not granted). Rests on "the room shows it" and "the room says what is missing".
A10 A person's second connect of `google` under the same label replaces their connection (same id, secret replaced,
    `needs` cleared) rather than 409 `too_many`. Rests on "connecting again over it replaces the secret and clears it".
A11 Userinfo is read at Google's `.../userinfo` with `Authorization: Bearer <new access token>` and answers the
    `email`; a grant that lacks the `email` scope is still stored when userinfo answers. Rests on "Google's userinfo
    for the account's address" and "A person who unticks a scope ... gets a connection".
A12 A grant with no refresh token (Google answers one only to an offline request) stores nothing. Rests on "the sealed
    secret is the refresh token".
A13 The callback outcome for a refusal is anything but `connected`; the tests pin `failed`, `cancelled` and
    `wrong_person` where the design's Discord model names them, and otherwise only that nothing was stored.
A14 `secret_version` and `needs` are columns of `connections` (the design names them); the access token, expiry and
    scopes columns are not named, so no test reads them.
A15 Two renewals in flight leave one winner: the tests hold the first refresh open (`FakeGoogle.in_refresh`) and run
    another pod's whole refresh inside it, which assumes no process-wide lock around a renewal.
"""

import base64
import hashlib
import logging
import os
import secrets
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlsplit

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.connections.connections import Connections
from ashley.connections.oauth import OAuthUnavailable
from ashley.connections.renewal import NeedsReconnect, Renewal
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import CLIENT_ID, CLIENT_SECRET, FakeGoogle

__all__ = ["NeedsReconnect", "OAuthUnavailable", "access_token"]


async def access_token(connection_id: int, household_id: int, person_id: int | None = None) -> str | None:
    """The build's `Renewal.access_token` service (A7's function is a service method, `NeedsReconnect` lives beside it)."""
    return await services.get(Renewal).access_token(connection_id, household_id, person_id)

T = TypeVar("T")
PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
START = "/api/connections/oauth/google/start"
CALLBACK = "/api/connections/oauth/google/callback"
REDIRECT_URI = PUBLIC + CALLBACK
OUTCOME = "connect"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/gmail.modify")


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


def app_client(url: str, fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch,
               configured: bool = True) -> Generator[TestClient]:
    """The real app on the database, every HTTP request of the process going to `fake`."""
    fake.install(monkeypatch)
    ids = {"google_oauth_client_id": CLIENT_ID, "google_oauth_client_secret": CLIENT_SECRET} if configured else {}
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY, **ids))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c


def in_app(client: TestClient, call: Callable[[], Awaitable[T]]) -> T:
    """Run `call` on the event loop the app's services live on."""
    portal = client.portal
    assert portal is not None
    return portal.call(call)


# --- the flow ------------------------------------------------------------------------------------------------------


def begin(client: TestClient, label: str = "", headers: dict[str, str] | None = None) -> httpx2.Response:
    return client.post(START, json={"kind": "google", "label": label}, headers=ORIGIN if headers is None else headers)


def start(client: TestClient, fake: FakeGoogle, label: str = "") -> tuple[str, str]:
    """Start a connect as the signed-in person and play the consent screen: (code, state)."""
    started = begin(client, label)
    assert started.status_code == 201, started.text
    return fake.authorize(started.json()["authorize_url"])


def back(client: TestClient, **query: str) -> str:
    done = client.get(CALLBACK, params=query)
    assert done.status_code == 302, done.text
    return done.headers["location"]


def outcome(location: str) -> str:
    parts = urlsplit(location)
    assert parts.path == "/connections", location
    return parse_qs(parts.query)[OUTCOME][0]


def connect(client: TestClient, fake: FakeGoogle, label: str = "") -> str:
    code, state = start(client, fake, label)
    return outcome(back(client, code=code, state=state))


def listed(client: TestClient) -> list[dict[str, Any]]:
    got = client.get("/api/connections")
    assert got.status_code == 200, got.text
    return [c for c in got.json()["connections"] if c["kind"] == "google"]


def the_google(client: TestClient) -> dict[str, Any]:
    found = listed(client)
    assert len(found) == 1, found
    return found[0]


def opened_secret(client: TestClient, people: People, connection_id: int, who: str = "alana") -> str:
    person = getattr(people, who)

    async def read() -> str:
        found = await services.get(Connections).opened(connection_id, people.home, person)
        assert found is not None
        return found.secret

    return in_app(client, read)


def fresh(client: TestClient, people: People, connection_id: int, who: str = "alana") -> str | None:
    """An access token for the connection, renewed if it is within the margin."""
    person = getattr(people, who)

    async def get() -> str | None:
        return await access_token(connection_id, people.home, person)

    return in_app(client, get)


def connected(client: TestClient, fake: FakeGoogle, people: People, who: str = "alana") -> tuple[int, str, str]:
    """Connect as `who` and return (connection id, the refresh token stored, the access token issued)."""
    as_(client, people, who)
    assert connect(client, fake) == "connected"
    cid = the_google(client)["id"]
    return cid, opened_secret(client, people, cid, who), fake.issued_access[-1]


# --- the database --------------------------------------------------------------------------------------------------


def pending(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM connect_pending"))


def pending_hashed(url: str, state: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM connect_pending WHERE state_sha256 = %s",
                      (hashlib.sha256(state.encode()).digest(),)))


def pending_owner(url: str) -> int:
    return int(scalar(url, "SELECT person_id FROM connect_pending"))


def age_pending(url: str) -> None:
    scalar(url, "UPDATE connect_pending SET created_at = created_at - interval '1 day' RETURNING 1")


def rows(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM connections WHERE kind = 'google'"))


def row_text(url: str) -> str:
    """Every stored connection and pending row as text: plaintext, or hex for a bytea column."""
    return "\n".join(str(scalar(url, f"SELECT coalesce(string_agg(t::text, E'\\n'), '') FROM {table} t"))
                     for table in ("connections", "connect_pending"))


def version(url: str, connection_id: int) -> int:
    return int(scalar(url, "SELECT secret_version FROM connections WHERE id = %s", (connection_id,)))


def needs(url: str, connection_id: int) -> str | None:
    found = scalar(url, "SELECT needs FROM connections WHERE id = %s", (connection_id,))
    return None if found is None else str(found)


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''}"
                     for r in caplog.records)


def all_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
