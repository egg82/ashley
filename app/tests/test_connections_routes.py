"""A household's connections end to end through the real app, a real database and a fake Sure: a person connects
the household's Sure, which another person of the household then sees, replaces and removes; a key Sure refuses, an
address that is not https or not Sure, or Sure not answering stores nothing; the key is never on the wire back nor in
a log line; another household sees none of it; without the app's key nothing can be connected."""

import base64
import hashlib
import os
import secrets
from collections.abc import Generator
from dataclasses import dataclass

import psycopg
import pytest
from ashley import logs, services
from ashley.api.connection_models import ConnectionRefused, ConnectionsResponse, HouseholdConnection
from ashley.api.models import ErrorResponse
from ashley.api.person import SESSION_COOKIE
from ashley.connections.connections import Connections
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from money_support import BASE, KEY, FakeSure
from connection_routes_support import delete_kind, put_kind

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()


@dataclass(frozen=True)
class Homes:
    alana: int
    sam: int
    alana_token: str
    sam_token: str
    kim_token: str


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
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        conn.execute("UPDATE people SET admin = true WHERE id = %s", (alana,))
        return Homes(alana, sam, _session(conn, alana, home, "sub-alana"), _session(conn, sam, home, "sub-sam"),
                     _session(conn, kim, other, "sub-kim"))


@pytest.fixture
def sure() -> FakeSure:
    return FakeSure()


def _client(db_url: str, homes: Homes, sure: FakeSure, key: str) -> Generator[TestClient]:
    services.unregister(Connections)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=key))
    services.register(Sure, sure.client())
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        as_(c, homes.alana_token)
        yield c
    services.unregister(Sure)
    services.unregister(Connections)


@pytest.fixture
def client(db_url: str, homes: Homes, sure: FakeSure) -> Generator[TestClient]:
    yield from _client(db_url, homes, sure, APP_KEY)


def as_(client: TestClient, token: str) -> None:
    client.cookies.set(SESSION_COOKIE, token, domain="ashley.test")


def connect(client: TestClient, base: str = BASE, key: str = KEY) -> HouseholdConnection | ConnectionRefused:
    got = put_kind(client, "sure", json={"base_url": base, "api_key": key}, headers=ORIGIN)
    if got.status_code == 400:
        return ConnectionRefused.model_validate(got.json())
    assert got.status_code == 200, got.text
    assert KEY not in got.text
    return HouseholdConnection.model_validate(got.json())


def listed(client: TestClient) -> ConnectionsResponse:
    got = client.get("/api/connections")
    assert got.status_code == 200
    return ConnectionsResponse.model_validate(got.json())


def test_a_person_connects_and_another_of_the_household_sees_and_removes_it(
        client: TestClient, homes: Homes, sure: FakeSure, db_url: str) -> None:
    empty = listed(client)
    assert empty.connections == [] and empty.can_connect
    made = connect(client, BASE + "/")
    assert isinstance(made, HouseholdConnection)
    assert made.base_url == BASE and made.added_by is not None and made.added_by.id == homes.alana
    assert sure.seen == [("/api/v1/accounts", {"per_page": "1"}, KEY)]
    as_(client, homes.sam_token)
    seen = listed(client)
    assert seen.connections == [made] and KEY not in client.get("/api/connections").text
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 204
    assert listed(client).connections == []
    gone = delete_kind(client, "sure", headers=ORIGIN)
    assert gone.status_code == 404 and ErrorResponse.model_validate(gone.json()).code == "not_found"
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_replacement_keeps_one_connection_named_for_who_replaced_it(client: TestClient, homes: Homes,
                                                                      sure: FakeSure) -> None:
    connect(client)
    as_(client, homes.sam_token)
    sure.key = "a-newer-key"
    made = connect(client, key="a-newer-key")
    assert isinstance(made, HouseholdConnection) and made.added_by is not None and made.added_by.id == homes.sam
    assert len(listed(client).connections) == 1


def test_another_household_sees_none_of_it(client: TestClient, homes: Homes) -> None:
    connect(client)
    as_(client, homes.kim_token)
    assert listed(client).connections == []
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 404


@pytest.mark.parametrize(("base", "status", "raw", "reason"), [
    ("http://money.test", 200, None, "bad_url"), ("https://", 200, None, "bad_url"),
    ("https://user:pw@money.test", 200, None, "bad_url"), ("https://money.test/?x=1", 200, None, "bad_url"),
    (BASE, 401, None, "key_refused"), (BASE, 302, None, "unreachable"), (BASE, 502, None, "unreachable"),
    (BASE, 404, None, "wrong_service"), (BASE, 200, b"<html>sign in</html>", "wrong_service")])
def test_a_connection_sure_does_not_answer_stores_nothing(client: TestClient, sure: FakeSure, db_url: str,
                                                          base: str, status: int, raw: bytes | None,
                                                          reason: str) -> None:
    sure.status, sure.raw = status, raw
    got = connect(client, base)
    assert isinstance(got, ConnectionRefused) and got.reason == reason
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0
    if reason == "bad_url":
        assert sure.seen == []


def test_a_key_sure_turns_away_is_refused_and_stores_nothing(client: TestClient, db_url: str) -> None:
    got = connect(client, key="not-the-key")
    assert isinstance(got, ConnectionRefused) and got.reason == "key_refused"
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_write_from_another_site_is_refused(client: TestClient) -> None:
    got = put_kind(client, "sure", json={"base_url": BASE, "api_key": KEY},
                     headers={"origin": "https://evil.test"})
    assert got.status_code == 403


def test_a_body_missing_the_address_does_not_echo_the_key_back(client: TestClient) -> None:
    got = put_kind(client, "sure", json={"api_key": KEY}, headers=ORIGIN)
    assert got.status_code == 400 and KEY not in got.text and got.json()["reason"] == "bad_url"


def test_a_malformed_address_or_key_does_not_echo_the_key_back(client: TestClient) -> None:
    long_address = put_kind(client, "sure", json={"base_url": "h" * 501, "api_key": KEY}, headers=ORIGIN)
    spaced_key = put_kind(client, "sure", json={"base_url": BASE, "api_key": f"{KEY} {KEY}"}, headers=ORIGIN)
    for got in (long_address, spaced_key):
        assert got.status_code == 422 and KEY not in got.text and "h" * 501 not in got.text


def test_not_signed_in_is_401(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/connections").status_code == 401


def test_without_the_apps_key_nothing_can_be_connected(db_url: str, homes: Homes, sure: FakeSure) -> None:
    for c in _client(db_url, homes, sure, ""):
        off = listed(c)
        assert off.connections == [] and not off.can_connect and len(off.offered) == 16
        got = put_kind(c, "sure", json={"base_url": BASE, "api_key": KEY}, headers=ORIGIN)
        assert got.status_code == 503 and sure.seen == []


def test_the_key_and_address_reach_no_log_line(client: TestClient, homes: Homes, sure: FakeSure,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    connect(client)
    sure.status = 401
    connect(client)
    listed(client)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert any("event=connections.connected" in ln for ln in lines)
    assert any("event=connections.refused" in ln for ln in lines)
    assert not any(KEY in ln or "money.test" in ln for ln in lines)
