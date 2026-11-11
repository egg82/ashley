"""Harness for the blind admin-role suite: the real app on a real database, sign-in through a fake provider that can say
who signs in and which groups the ID token names, sessions made by sign-in or by row, and the connection kinds with the
provider-key check answered locally. Everything is driven through the routes and the database's own columns."""

import base64
import hashlib
import os
import secrets
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from typing import Any

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKind, ConnectionKinds, Refusal
from ashley.main import create_app
from ashley.people import admin
from ashley.signin.oidc import Oidc
from ashley.settings import Settings
from ashley.wiring import CONNECTION_KINDS
from contract.conversations_support import scalar
from fastapi import FastAPI
from fastapi.testclient import TestClient
from signin_support import CLIENT, ISSUER, FakeIdp, oidc_for

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
GROUP = "ashley-admins"
APP_KEY = base64.b64encode(os.urandom(32)).decode()
FIRST = 1


@dataclass(frozen=True)
class World:
    """Three people of the first household (ids ascending: alana, sam, ivy) and one of another (kim)."""

    home: int
    other: int
    alana: int
    sam: int
    ivy: int
    kim: int

    def sub(self, person: int) -> str:
        return f"sub-{person}"


@dataclass
class MultiIdp(FakeIdp):
    """A fake provider whose next sign-in is decided per code: `authorize_as` says who signs in with that code and which
    groups the ID token names (None: no `groups` claim at all)."""

    who: dict[str, tuple[str, list[str] | None]] = field(default_factory=dict[str, tuple[str, list[str] | None]])

    def authorize_as(self, url: str, sub: str, groups: list[str] | None = None) -> tuple[str, str]:
        code, state = self.authorize(url)
        self.who[code] = (sub, groups)
        return code, state

    def _token(self, form: dict[str, list[str]]) -> httpx2.Response:
        sub, groups = self.who.pop(form["code"][0], (self.sub, None))
        self.sub = sub
        self.claims = {} if groups is None else {"groups": groups}
        return super()._token(form)


def make_world(url: str) -> World:
    with psycopg.connect(url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, ivy = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                           admin.add_person(conn, home, "Ivy"))
        kim = admin.add_person(conn, other, "Kim")
        world = World(home, other, alana, sam, ivy, kim)
        for person in (alana, sam, ivy, kim):
            admin.add_account(conn, person, "oidc", world.sub(person))
    assert (world.home, world.other) == (FIRST, 2)
    assert world.alana < world.sam < world.ivy
    return world


def set_admin(url: str, person: int, value: bool = True) -> None:
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE people SET admin = %s WHERE id = %s", (value, person))


def admin_ids(url: str) -> list[int]:
    with psycopg.connect(url) as conn:
        return [r[0] for r in conn.execute("SELECT id FROM people WHERE admin ORDER BY id").fetchall()]


def session_for(url: str, world: World, person: int) -> str:
    """A live session cookie value for `person`, made by row: no sign-in, so `sessions.admin` is its default."""
    household = world.other if person == world.kim else world.home
    token = secrets.token_urlsafe(16)
    account = scalar(url, "SELECT id FROM accounts WHERE person_id = %s", (person,))
    with psycopg.connect(url) as conn:
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, household))
    return token


def as_(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")


def no_client(app: FastAPI) -> bool:
    return False


def _kinds(first_household_deployment: tuple[str, ...]) -> ConnectionKinds:
    async def answered(base: str, key: str, person_id: int) -> Refusal | None:
        return None

    kinds: list[ConnectionKind] = []
    for k in CONNECTION_KINDS:
        if k.deployment:
            k = replace(k, check=answered)
        if k.name in first_household_deployment:
            k = replace(k, deployment=True)
        kinds.append(k)
    return ConnectionKinds(tuple(kinds))


def build(url: str, idp: MultiIdp, monkeypatch: pytest.MonkeyPatch, group: str = "") -> FastAPI:
    """The real app, signing in through `idp`; `group` is `ADMIN_GROUP`, set on the settings and on the provider's client."""
    monkeypatch.setattr("ashley.main.mount_client", no_client)
    services.unregister(Connections)
    app = create_app(Settings(database_url=url, build_version="t", oidc_issuer=ISSUER, oidc_client_id=CLIENT.client_id,
                              oidc_client_secret=CLIENT.client_secret, public_url=PUBLIC, admin_group=group,
                              connections_key=APP_KEY))
    services.register(Oidc, oidc_for(idp, replace(CLIENT, admin_group=group)))
    return app


class running:
    """The app running against `url`, signing in through `idp`, as a context manager yielding its client. `group` is
    `ADMIN_GROUP`; `deployment` names the extra kinds this registry marks `deployment`, so settings and resources, which
    the provider-key kinds have none of, can be gated too."""

    def __init__(self, url: str, idp: MultiIdp, monkeypatch: pytest.MonkeyPatch, group: str = "",
                 deployment: tuple[str, ...] = ("home_assistant", "google")) -> None:
        self.app = build(url, idp, monkeypatch, group)
        self.deployment = deployment
        self.client = TestClient(self.app, base_url=PUBLIC, follow_redirects=False)

    def __enter__(self) -> TestClient:
        self.client.__enter__()
        services.unregister(ConnectionKinds)
        services.register(ConnectionKinds, _kinds(self.deployment))
        return self.client

    def __exit__(self, *exc: object) -> None:
        self.client.__exit__(*exc)
        services.unregister(Connections)
        services.unregister(ConnectionKinds)
        services.unregister(Oidc)


def sign_in(client: TestClient, idp: MultiIdp, sub: str, groups: list[str] | None = None) -> httpx2.Response:
    """A browser signs in as `sub`; the client keeps the session cookie. Returns the callback's answer."""
    started = client.get("/api/auth/signin", params={"next": "/"})
    assert started.status_code == 302, started.text
    code, state = idp.authorize_as(started.headers["location"], sub, groups)
    return client.get("/api/auth/callback", params={"code": code, "state": state})


def token_of(client: TestClient) -> str:
    token = client.cookies.get(SESSION_COOKIE)
    assert token, "the browser holds no session"
    return token


def me(client: TestClient) -> dict[str, Any]:
    got = client.get("/api/me")
    assert got.status_code == 200, got.text
    return got.json()["person"]


def people_listing(client: TestClient) -> dict[str, Any]:
    got = client.get("/api/people")
    assert got.status_code == 200, got.text
    return got.json()


def admin_flags(client: TestClient) -> dict[int, bool]:
    return {p["id"]: p["admin"] for p in people_listing(client)["people"]}


def put_admin(client: TestClient, person: int, value: bool) -> httpx2.Response:
    return client.put(f"/api/people/{person}/admin", json={"admin": value}, headers=ORIGIN)


def add_connection(client: TestClient, household: int, kind: str, person: int, base: str, secret: str = "sk-held") -> int:
    async def make() -> int:
        return (await services.get(Connections).add(household, kind, "", base, secret, person)).id

    assert client.portal is not None
    return client.portal.call(make)


def codes(response: httpx2.Response) -> tuple[int, str | None]:
    try:
        return response.status_code, response.json().get("code")
    except ValueError:
        return response.status_code, None


@pytest.fixture
def idp() -> MultiIdp:
    return MultiIdp()


@pytest.fixture
def world(db_url: str) -> World:
    return make_world(db_url)


@pytest.fixture
def app_mode(db_url: str, world: World, idp: MultiIdp, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    with running(db_url, idp, monkeypatch) as client:
        yield client


@pytest.fixture
def provider_mode(db_url: str, world: World, idp: MultiIdp, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    with running(db_url, idp, monkeypatch, GROUP) as client:
        yield client
