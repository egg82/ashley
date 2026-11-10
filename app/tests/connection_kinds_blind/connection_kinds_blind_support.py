"""Pieces of the connection-kinds blind tests: one fake HTTP world for the four services (Sure, Home Assistant, GitLab,
GitHub) behind `httpx2.MockTransport` that records every request, two households with people and sessions on a real
database, the real app on it, and the real Postgres-backed Connections for reads made outside the app."""

import asyncio
import base64
import hashlib
import logging
import os
import secrets
from collections.abc import AsyncGenerator, Coroutine, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

import httpx2
import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.codehost.config import CodeHostConfig
from ashley.codehost.github import GitHubHost
from ashley.codehost.gitlab import GitLabHost
from ashley.codehost.host import CodeHost
from ashley.codehost.routed import RoutedCodeHost
from ashley.codehost.wire import Wire
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKind, ConnectionKinds
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.rest_automations import AutomationsConfig
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.sure.client import HttpSure, Sure
from ashley.wiring import CONNECTION_KINDS
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from connection_legacy_support import put_of

T = TypeVar("T")

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
CODE_HOSTS = CodeHostConfig(timeout_s=5.0, projects_max=5, tree_max=5, read_bytes=64, snapshot_max_bytes=2000)
HA_CONFIG = AutomationsConfig(timeout_s=2.0, entity_tries=1, entity_wait_s=0.0)

KIND_NAMES = ("sure", "home_assistant", "gitlab", "github")
ADDRESSES = {"sure": "https://money.test", "home_assistant": "http://ha.test:8123", "gitlab": "https://gitlab.test"}
HOSTS = {"money.test": "sure", "ha.test": "home_assistant", "gitlab.test": "gitlab", "api.github.com": "github"}
SECRETS = {"sure": "sure-key-0001-SECRETKEY", "home_assistant": "ha-token-0001-SECRETKEY",
           "gitlab": "gl-token-0001-SECRETKEY", "github": "gh-token-0001-SECRETKEY"}
OTHER_SECRETS = {name: value.replace("0001", "0002") for name, value in SECRETS.items()}


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def kind_named(name: str) -> ConnectionKind:
    return next(k for k in CONNECTION_KINDS if k.name == name)


def body_for(kind: str, secret: str | None = None, address: str | None = None) -> dict[str, str]:
    """The request body a kind takes: its address when it has one a person types, its own secret field."""
    declared = kind_named(kind)
    body = {declared.secret_field: secret if secret is not None else SECRETS[kind]}
    if declared.fixed_address is None:
        body["base_url"] = address if address is not None else ADDRESSES[kind]
    return body


# --- the fake services --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    service: str
    method: str
    path: str
    secret: str


def _html() -> httpx2.Response:
    return httpx2.Response(200, content=b"<html><body>a login page</body></html>", headers={"content-type": "text/html"})


def _json(body: object, headers: dict[str, str] | None = None) -> httpx2.Response:
    import json
    return httpx2.Response(200, content=json.dumps(body).encode(),
                           headers={"content-type": "application/json", **(headers or {})})


def _account() -> dict[str, object]:
    return {"id": "0b6f5a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b", "name": "Checking", "balance": "$1.00", "balance_cents": 100,
            "cash_balance": "$1.00", "cash_balance_cents": 100, "currency": "USD", "classification": "asset",
            "account_type": "depository", "subtype": "checking", "status": "active", "institution_name": "Bank",
            "institution_domain": "bank.test", "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-10-30T00:00:00Z"}


@dataclass
class Fakes:
    """The four services. `accepts[service]` is the secrets it answers for (anything else is 401); `mode[service]` is
    `ok`, `down` (connection refused), `missing` (404), `html` (a 200 web page, what answers at an address that is not that service) or
    `refuse` (401 for every secret)."""

    seen: list[Seen] = field(default_factory=list[Seen])
    accepts: dict[str, set[str]] = field(default_factory=lambda: {n: {SECRETS[n], OTHER_SECRETS[n]} for n in KIND_NAMES})
    mode: dict[str, str] = field(default_factory=lambda: {n: "ok" for n in KIND_NAMES})
    other_hosts: list[str] = field(default_factory=list[str])

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        service = HOSTS.get(host)
        if service is None:
            self.other_hosts.append(host)
            return httpx2.Response(404, json={"message": "no such host"})
        auth = request.headers.get("authorization", "")
        secret = (request.headers.get("x-api-key") or request.headers.get("private-token")
                  or (auth[len("Bearer "):] if auth.startswith("Bearer ") else ""))
        self.seen.append(Seen(service, request.method, request.url.path, secret))
        mode = self.mode[service]
        if mode == "down":
            raise httpx2.ConnectError("down")
        if mode == "refuse" or secret not in self.accepts[service]:
            return httpx2.Response(401, json={"message": "401 Unauthorized"})
        if mode == "html":
            return _html()
        if mode == "missing":
            return httpx2.Response(404, json={"message": "404 Not Found"})
        return getattr(self, "_" + service)(request.url.path)

    def _sure(self, path: str) -> httpx2.Response:
        pagination = {"page": 1, "per_page": 25, "total_count": 1, "total_pages": 1}
        bodies: dict[str, object] = {"/api/v1/accounts": {"accounts": [_account()], "pagination": pagination}}
        if path in bodies:
            return _json(bodies[path])
        return httpx2.Response(404, json={"error": "not_found"})

    def _home_assistant(self, path: str) -> httpx2.Response:
        if path in ("/api/", "/api"):
            return _json({"message": "API running."})
        if path == "/api/states":
            return _json([{"entity_id": "light.hall", "state": "on", "attributes": {"friendly_name": "Hall"}}])
        if path == "/api/config":
            return _json({"latitude": 1.0, "longitude": 2.0, "time_zone": "UTC"})
        return _json({})

    def _gitlab(self, path: str) -> httpx2.Response:
        if path.endswith("/api/v4/user"):
            return _json({"id": 1, "username": "someone"})
        if path.endswith("/api/v4/projects"):
            return _json([{"id": 11, "path_with_namespace": "grp/proj", "description": "d", "default_branch": "main",
                           "name": "proj"}], {"x-page": "1", "x-per-page": "30", "x-next-page": ""})
        return httpx2.Response(404, json={"message": "404 Not Found"})

    def _github(self, path: str) -> httpx2.Response:
        if path == "/user":
            return _json({"login": "someone", "id": 1})
        if path == "/user/repos":
            return _json([{"id": 21, "full_name": "me/site", "description": "d", "default_branch": "main",
                           "private": True}])
        return httpx2.Response(404, json={"message": "Not Found"})

    def http(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), follow_redirects=False)

    def sure(self) -> Sure:
        return HttpSure(self.http(), 5)

    def code_host(self) -> CodeHost:
        wire = Wire(self.http(), CODE_HOSTS.timeout_s)
        return RoutedCodeHost({"gitlab": GitLabHost(wire, CODE_HOSTS), "github": GitHubHost(wire, CODE_HOSTS)})

    def homes(self, connections: Connections) -> Homes:
        def connect(base_url: str, token: str) -> HomeAssistant:
            return HomeAssistant(httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), base_url=base_url,
                                                    headers={"Authorization": f"Bearer {token}"}))

        return ConnectedHomes(connections, HA_CONFIG, connect)

    def wire_into(self, connections: Connections) -> None:
        services.register(Sure, self.sure())
        services.register(CodeHost, self.code_host())
        services.register(Homes, self.homes(connections))

    def count(self, service: str) -> int:
        return sum(1 for s in self.seen if s.service == service)

    def secrets(self) -> set[str]:
        return {s.secret for s in self.seen}


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


def app_client(url: str, fakes: Fakes, key: str = APP_KEY) -> Generator[TestClient]:
    """The real app on the database with the fake world wired in once it has started."""
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=key))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        fakes.wire_into(services.get(Connections))
        yield c


def rows(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM connections"))


def stored_at(url: str, household: int, kind: str, person: int | None = None) -> datetime:
    return scalar(url, "SELECT checked_at FROM connections WHERE household_id = %s AND kind = %s "
                       "AND person_id IS NOT DISTINCT FROM %s", (household, kind, person))


def age(url: str, household: int, kind: str, person: int | None = None) -> datetime:
    """Move a stored connection's `checked_at` an hour into the past and return it, so a later move is unmistakable."""
    return scalar(url, "UPDATE connections SET checked_at = checked_at - interval '1 hour' WHERE household_id = %s "
                       "AND kind = %s AND person_id IS NOT DISTINCT FROM %s RETURNING checked_at",
                  (household, kind, person))


def owner(kind: str, person: int) -> int | None:
    """The `person_id` a stored connection of `kind` carries when `person` made it."""
    return person if kind_named(kind).default_holder == "person" else None


# --- Connections without the app --------------------------------------------------------------------------------------


KEY = os.urandom(32)


@asynccontextmanager
async def connections(url: str, kinds: tuple[ConnectionKind, ...] = CONNECTION_KINDS) -> AsyncGenerator[Connections]:
    """The real Postgres Connections registered with the locator, over the registered `kinds`."""
    database = PoolDatabase(url)
    await database.open()
    service = PostgresConnections(database, Sealer({1: KEY}, current=1))
    services.register(ConnectionKinds, ConnectionKinds(kinds))
    services.register(Connections, service)
    try:
        yield service
    finally:
        await database.close()


async def hold(c: Connections, household: int, person: int, kind: str, secret: str | None = None) -> int:
    """Store `person`'s connection of `kind` in `household` as a checked PUT would, returning its id."""
    base = kind_named(kind).fixed_address or ADDRESSES[kind]
    made = await put_of(c, household, kind, base, secret if secret is not None else SECRETS[kind], person)
    return made.id


def log_text(caplog: pytest.LogCaptureFixture, only: str = "") -> str:
    out: list[str] = []
    for r in caplog.records:
        if only and not r.name.startswith(only):
            continue
        out.append(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''}")
    return "\n".join(out)


def all_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
