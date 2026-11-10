"""Helpers for Proton Bridge's tests: the record on a real database, a proton connection to hang an account on, and a fake
Kubernetes API (pods and Secrets, through httpx2's MockTransport so `KubeApi` runs its real HTTP code)."""

import base64
import hashlib
import json
import logging
import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
import psycopg
from ashley import services
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.mail.proton_bridge_postgres import PostgresProtonBridge
from ashley.mail.proton_login import LoginStep, ProtonLogin
from ashley.mail.proton_kind import ADDRESS, PROTON
from ashley.people import admin
from ashley.runs.kube_api import KubeApi
from ashley.wiring import CONNECTION_KINDS

KEY = os.urandom(32)
NAMESPACE = "ashley-mail"


def with_proton_kind() -> None:
    services.register(ConnectionKinds, ConnectionKinds((*CONNECTION_KINDS, PROTON)))


@asynccontextmanager
async def bridge_on(url: str, key: bytes = KEY) -> AsyncGenerator[PostgresProtonBridge]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresProtonBridge(database, Sealer({VERSION: key}))
    finally:
        await database.close()


async def proton_connection(url: str, label: str = "") -> int:
    """A proton connection of a new household's person; its id."""
    with_proton_kind()
    with psycopg.connect(url) as conn:
        household = admin.add_household(conn, f"h{os.urandom(3).hex()}", "UTC")
        person = admin.add_person(conn, household, "Alana")
    database = PoolDatabase(url)
    await database.open()
    try:
        added = await PostgresConnections(database, Sealer({VERSION: KEY})).add(
            household, PROTON.name, label, ADDRESS, "bridge-password", person)
    finally:
        await database.close()
    return added.id


@dataclass
class BridgeKube:
    """Pods and Secrets of one namespace, in memory. A created pod is `Running` until a test sets its phase."""

    token_file: Path
    pods: dict[str, dict[str, Any]] = field(default_factory=lambda: dict[str, dict[str, Any]]())
    secrets: dict[str, dict[str, Any]] = field(default_factory=lambda: dict[str, dict[str, Any]]())
    calls: list[str] = field(default_factory=lambda: list[str]())
    broken: bool = False

    def api(self) -> KubeApi:
        self.token_file.write_text("token")
        client = httpx2.AsyncClient(base_url="https://kube.test", transport=httpx2.MockTransport(self.handle))
        return KubeApi(client, str(self.token_file))

    def phase(self, name: str, phase: str) -> None:
        self.pods[name]["status"] = {"phase": phase}

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.broken:
            return httpx2.Response(500, json={})
        parts = request.url.path.strip("/").split("/")
        store = self.pods if parts[4] == "pods" else self.secrets
        name = parts[5] if len(parts) > 5 else None
        self.calls.append(f"{request.method} {parts[4]}{'/' + name if name else ''}")
        if request.method == "POST":
            body = json.loads(request.content)
            if body["metadata"]["name"] in store:
                return httpx2.Response(409, json={})
            if store is self.secrets:
                body["data"] = {k: base64.b64encode(v.encode()).decode() for k, v in body.pop("stringData").items()}
            else:
                body["status"] = {"phase": "Running"}
            store[body["metadata"]["name"]] = body
            return httpx2.Response(201, json=body)
        if name is None:
            wanted = request.url.params.get("labelSelector", "").partition("=")
            items = [o for o in store.values() if o["metadata"]["labels"].get(wanted[0]) == wanted[2]]
            return httpx2.Response(200, json={"items": items})
        if name not in store:
            return httpx2.Response(404, json={})
        if request.method == "DELETE":
            del store[name]
        return httpx2.Response(200, json=store.get(name, {}))


def logged(caplog: Any) -> list[tuple[str, dict[str, Any]]]:
    """Each structured line captured, as its event and fields."""
    return [(r.getMessage(), dict[str, Any](getattr(r, "fields", {}))) for r in caplog.records
            if isinstance(r, logging.LogRecord)]


def signed_in_token(url: str, household: int, person: int, sub: str) -> str:
    """A live session for `person`, as its cookie value."""
    with psycopg.connect(url) as conn:
        account = admin.add_account(conn, person, "oidc", sub)
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, household))
    return token


@dataclass
class ScriptedLogin(ProtonLogin):
    """Bridge's login as a script: each call answers the next step queued, and is recorded without its secrets."""

    steps: list[LoginStep] = field(default_factory=lambda: list[LoginStep]())
    calls: list[str] = field(default_factory=lambda: list[str]())
    seen: list[str] = field(default_factory=lambda: list[str]())

    async def begin(self, username: str, password: str) -> LoginStep:
        self.calls.append("begin")
        self.seen += [username, password]
        return self.steps.pop(0)

    async def verified(self, password: str) -> LoginStep:
        self.calls.append("verified")
        self.seen.append(password)
        return self.steps.pop(0)

    async def second_factor(self, code: str) -> LoginStep:
        self.calls.append("second_factor")
        self.seen.append(code)
        return self.steps.pop(0)

    async def mailbox_password(self, password: str) -> LoginStep:
        self.calls.append("mailbox_password")
        self.seen.append(password)
        return self.steps.pop(0)

    async def forget(self, user_id: str) -> None:
        self.calls.append(f"forget {user_id}")
