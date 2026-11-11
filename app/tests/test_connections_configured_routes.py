"""A kind whose deployment-side setting is absent (herdr's client certificate, Proton Mail Bridge's image) is not offered
and cannot be added, but a row of it already stored is still listed and can be removed."""

import asyncio
import base64
import hashlib
import os
import secrets
from collections.abc import Generator

import psycopg
import pytest
from ashley import services
from ashley.api.connection_models import ConnectionsResponse
from ashley.api.person import SESSION_COOKIE
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.pool import PoolDatabase
from ashley.herdr.kind import HERDR
from ashley.mail.proton_kind import ADDRESS, PROTON
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.wiring import CONNECTION_KINDS, configured_kinds
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = os.urandom(32)
PIN = "ab" * 32
HERDR_ADDRESS = f"https://vm.test:7843#sha256={PIN}"


@pytest.fixture
def household(db_url: str) -> Generator[tuple[int, str]]:
    with psycopg.connect(db_url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        person = admin.add_person(conn, home, "Alana")
        account = admin.add_account(conn, person, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
    yield person, token
    services.unregister(Connections)


def _store_rows(db_url: str, person: int) -> None:
    """One herdr and one Proton connection of the person's, stored while both kinds are registered as configured."""
    async def store() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            services.register(ConnectionKinds, ConnectionKinds((*CONNECTION_KINDS, PROTON)))
            connections = PostgresConnections(database, Sealer({VERSION: APP_KEY}))
            with psycopg.connect(db_url) as conn:
                home = conn.execute("SELECT household_id FROM people WHERE id = %s", (person,)).fetchone()
            assert home is not None
            await connections.add(home[0], HERDR.name, "mine", HERDR_ADDRESS, "token", person)
            await connections.add(home[0], PROTON.name, "mail", ADDRESS, "password", person)
        finally:
            await database.close()
    asyncio.run(store())


def _client(db_url: str, token: str, **settings: str) -> Generator[TestClient]:
    services.unregister(Connections)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC,
                              connections_key=base64.b64encode(APP_KEY).decode(), **settings))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
        yield c


def _listed(client: TestClient) -> ConnectionsResponse:
    got = client.get("/api/connections")
    assert got.status_code == 200
    return ConnectionsResponse.model_validate(got.json())


def test_without_the_settings_the_kinds_are_not_offered_nor_added(db_url: str, household: tuple[int, str]) -> None:
    _, token = household
    for client in _client(db_url, token):
        offered = {k.name for k in _listed(client).offered}
        assert "sure" in offered and not offered & {"herdr", "proton"}
        for kind in ("herdr", "proton"):
            got = client.post("/api/connections", json={"kind": kind, "label": "x", "base_url": HERDR_ADDRESS,
                                                        "token": "t"}, headers=ORIGIN)
            assert got.status_code == 404


def test_with_the_herdr_certificate_the_herdr_kind_is_offered(db_url: str, household: tuple[int, str]) -> None:
    _, token = household
    for client in _client(db_url, token, herdr_client_cert_file="/cert", herdr_client_key_file="/key"):
        offered = {k.name for k in _listed(client).offered}
        assert "herdr" in offered and "proton" not in offered


def test_a_stored_row_of_an_unoffered_kind_is_listed_and_removable(db_url: str, household: tuple[int, str]) -> None:
    person, token = household
    _store_rows(db_url, person)
    for client in _client(db_url, token):
        shown = _listed(client)
        assert sorted(c.kind for c in shown.connections) == ["herdr", "proton"]
        assert not {k.name for k in shown.offered} & {"herdr", "proton"}
        for c in shown.connections:
            assert client.delete(f"/api/connections/{c.id}", headers=ORIGIN).status_code == 204
        assert _listed(client).connections == []


def test_the_kinds_are_configured_by_their_settings() -> None:
    def configured(**settings: str) -> dict[str, bool]:
        return {k.name: k.configured for k in configured_kinds(Settings(database_url="x", build_version="t", **settings))
                if k.name in ("herdr", "proton")}
    assert configured() == {"herdr": False, "proton": False}
    assert configured(herdr_client_cert_file="/c", herdr_client_key_file="/k")["herdr"]
