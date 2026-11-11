"""The connections routes and deployment kinds: only the first household is offered a model provider's kind and any other
household adding one gets 404 with nothing stored; the first household's admin adds one at its fixed address with no `base_url`; a key the
kind's `check` refuses is 400 and stores nothing; a key is in no response (add, list, replace) and in no log line."""

import base64
import hashlib
import logging
import os
import secrets
from collections.abc import Generator
from dataclasses import dataclass

import psycopg
import pytest
from ashley import services
from ashley.api.connection_models import ConnectionsResponse
from ashley.api.person import SESSION_COOKIE
from ashley.connections.connections import Connections
from ashley.connections.kinds import FIRST_HOUSEHOLD, ConnectionKinds, Refusal
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from pkb_support import A, deployment_kind

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
KEY = "sk-provider-key-ZZZZ-1234567890"
REFUSED = "sk-refused-key-QQQQ-1234567890"


@dataclass(frozen=True)
class Homes:
    first_token: str
    other_token: str


def _session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "oidc", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


@pytest.fixture
def homes(db_url: str) -> Homes:
    with psycopg.connect(db_url) as conn:
        first, other = admin.add_household(conn, "home", "UTC"), admin.add_household(conn, "other", "UTC")
        assert first == FIRST_HOUSEHOLD
        alana = admin.add_person(conn, first, "Alana")
        conn.execute("UPDATE people SET admin = true WHERE id = %s", (alana,))
        return Homes(_session(conn, alana, first, "sub-a"),
                     _session(conn, admin.add_person(conn, other, "Kim"), other, "sub-k"))


async def _check(url: str, key: str, person: int) -> Refusal | None:
    return "key_refused" if key == REFUSED else None


@pytest.fixture
def client(db_url: str) -> Generator[TestClient]:
    services.unregister(Connections)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        kind = deployment_kind(A, check=_check)
        services.register(ConnectionKinds, ConnectionKinds(services.get(ConnectionKinds).all() + (kind,)))
        yield c
    services.unregister(Connections)


def as_(client: TestClient, token: str) -> None:
    client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")


def offered(client: TestClient) -> list[str]:
    got = client.get("/api/connections")
    assert got.status_code == 200 and KEY not in got.text
    return [k.name for k in ConnectionsResponse.model_validate(got.json()).offered]


def test_only_the_first_household_is_offered_the_deployment_kind(client: TestClient, homes: Homes) -> None:
    as_(client, homes.first_token)
    assert A in offered(client)
    as_(client, homes.other_token)
    names = offered(client)
    assert A not in names and names, "the other household still sees the kinds it may connect"


def test_another_household_adding_a_deployment_kind_is_404_and_nothing_is_stored(
        client: TestClient, homes: Homes, db_url: str) -> None:
    as_(client, homes.other_token)
    got = client.post("/api/connections", json={"kind": A, "label": "", "api_key": KEY}, headers=ORIGIN)
    assert got.status_code == 404 and KEY not in got.text
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_the_first_household_adds_one_at_the_kinds_address_and_no_response_carries_the_key(
        client: TestClient, homes: Homes, db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    as_(client, homes.first_token)
    with caplog.at_level(logging.DEBUG):
        made = client.post("/api/connections", json={"kind": A, "label": "", "api_key": KEY}, headers=ORIGIN)
        assert made.status_code == 201, made.text
        assert made.json()["base_url"] == f"https://api.{A}.test" and KEY not in made.text
        listed = client.get("/api/connections")
        assert KEY not in listed.text and A in [c["kind"] for c in listed.json()["connections"]]
        replaced = client.put(f"/api/connections/{made.json()['id']}", json={"api_key": KEY + "2"}, headers=ORIGIN)
        assert replaced.status_code == 200 and KEY not in replaced.text and KEY + "2" not in replaced.text
    everything = caplog.text + repr([r.__dict__ for r in caplog.records])
    assert KEY not in everything and KEY + "2" not in everything
    stored = bytes(scalar(db_url, "SELECT secret FROM connections WHERE kind = %s", (A,)))
    assert KEY.encode() not in stored


def test_a_key_the_kinds_check_refuses_is_400_and_stores_nothing(client: TestClient, homes: Homes, db_url: str) -> None:
    as_(client, homes.first_token)
    got = client.post("/api/connections", json={"kind": A, "label": "", "api_key": REFUSED}, headers=ORIGIN)
    assert got.status_code == 400 and REFUSED not in got.text
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0
