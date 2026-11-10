"""Connections through the real app on a real database and a fake Sure: the typed refusals, nothing stored on a
refusal, the key never on the wire or in a log, any member may add/replace/remove, another household sees nothing."""

import base64
import hashlib
import os
import secrets
from collections.abc import Generator
from dataclasses import dataclass

import psycopg
import pytest
from httpx2 import Response
from ashley import logs, services
from ashley.api.connection_models import ConnectionRefused, ConnectionsResponse, HouseholdConnection
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.sure.client import Sure
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
    tokens: dict[str, str]


def session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "authentik", sub)
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
        return Homes(alana, sam, {"alana": session(conn, alana, home, "a"), "sam": session(conn, sam, home, "s"),
                                 "kim": session(conn, kim, other, "k")})


@pytest.fixture
def sure() -> FakeSure:
    return FakeSure()


def app_client(db_url: str, sure: FakeSure, key: str) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=key))
    services.register(Sure, sure.client())
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c


@pytest.fixture
def client(db_url: str, homes: Homes, sure: FakeSure) -> Generator[TestClient]:
    for c in app_client(db_url, sure, APP_KEY):
        as_(c, homes, "alana")
        yield c


def as_(client: TestClient, homes: Homes, who: str) -> None:
    client.cookies.set(SESSION_COOKIE, homes.tokens[who], domain="ashley.test")


def put(client: TestClient, base: str = BASE, key: str = KEY) -> Response:
    return put_kind(client, "sure", json={"base_url": base, "api_key": key}, headers=ORIGIN)


def count(db_url: str) -> int:
    return int(scalar(db_url, "SELECT count(*) FROM connections"))


def test_connecting_returns_the_connection_without_the_key(client: TestClient, homes: Homes, db_url: str) -> None:
    got = put(client)
    assert got.status_code == 200 and KEY not in got.text
    made = HouseholdConnection.model_validate(got.json())
    assert made.kind == "sure" and made.base_url == BASE and made.added_by is not None
    assert made.added_by.id == homes.alana
    assert count(db_url) == 1


def test_it_is_checked_against_sure_with_the_key_before_it_is_stored(client: TestClient, sure: FakeSure) -> None:
    put(client)
    assert sure.seen and all(path.startswith("/api/v1/") and key == KEY for path, _, key in sure.seen)


@pytest.mark.parametrize(("status", "raw", "reason"), [
    (200, None, "ok"), (401, None, "key_refused"), (403, None, "key_refused"), (302, None, "unreachable"),
    (500, None, "unreachable"), (404, None, "wrong_service"), (200, b"<html>sign in</html>", "wrong_service")])
def test_each_refusal_is_typed_and_stores_nothing(client: TestClient, sure: FakeSure, db_url: str, status: int,
                                                  raw: bytes | None, reason: str) -> None:
    sure.status, sure.raw = status, raw
    got = put(client)
    if reason == "ok":
        assert got.status_code == 200
        return
    assert got.status_code == 400
    assert ConnectionRefused.model_validate(got.json()).reason == reason
    assert KEY not in got.text
    assert count(db_url) == 0


@pytest.mark.parametrize("base", ["http://money.test", "money.test", "https://", "https://u:p@money.test",
                                  "https://money.test/?a=1", "https://money.test/#x"])
def test_a_bad_address_is_bad_url_and_asks_sure_nothing(client: TestClient, sure: FakeSure, db_url: str,
                                                        base: str) -> None:
    got = put(client, base)
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "bad_url"
    assert sure.seen == [] and count(db_url) == 0


def test_a_refused_replacement_leaves_the_old_connection(client: TestClient, sure: FakeSure, db_url: str) -> None:
    assert put(client).status_code == 200
    before = bytes(scalar(db_url, "SELECT secret FROM connections"))
    assert put(client, key="wrong-key").status_code == 400
    assert bytes(scalar(db_url, "SELECT secret FROM connections")) == before and count(db_url) == 1


def test_the_stored_secret_is_sealed_and_never_the_key(client: TestClient, db_url: str) -> None:
    put(client)
    stored = bytes(scalar(db_url, "SELECT secret FROM connections"))
    assert stored and KEY.encode() not in stored and base64.b64encode(KEY.encode()) not in stored


def test_any_member_sees_replaces_and_removes_it(client: TestClient, homes: Homes, sure: FakeSure,
                                                 db_url: str) -> None:
    assert put(client).status_code == 200
    as_(client, homes, "sam")
    seen = ConnectionsResponse.model_validate(client.get("/api/connections").json())
    assert [c.base_url for c in seen.connections] == [BASE] and seen.can_connect
    sure.key = "newer"
    replaced = put(client, "https://money2.test", "newer")
    assert replaced.status_code == 200 and "newer" not in replaced.text
    got = ConnectionsResponse.model_validate(client.get("/api/connections").json())
    assert [(c.base_url, c.added_by.id if c.added_by else None) for c in got.connections] == [
        ("https://money2.test", homes.sam)]
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 204
    assert count(db_url) == 0
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 404


def test_the_key_is_on_no_read_back(client: TestClient) -> None:
    put(client)
    for got in (client.get("/api/connections"), put(client)):
        body = got.json()
        shown = str(body["connections"] if "connections" in body else body)
        assert KEY not in got.text and "api_key" not in shown


def test_another_household_sees_nothing_and_cannot_remove(client: TestClient, homes: Homes, db_url: str) -> None:
    put(client)
    as_(client, homes, "kim")
    assert ConnectionsResponse.model_validate(client.get("/api/connections").json()).connections == []
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 404
    assert count(db_url) == 1


def test_each_household_holds_its_own(client: TestClient, homes: Homes, sure: FakeSure, db_url: str) -> None:
    put(client)
    as_(client, homes, "kim")
    put(client, "https://kims.test")
    assert count(db_url) == 2
    assert [c.base_url for c in ConnectionsResponse.model_validate(client.get("/api/connections").json()).connections
            ] == ["https://kims.test"]
    as_(client, homes, "alana")
    assert [c.base_url for c in ConnectionsResponse.model_validate(client.get("/api/connections").json()).connections
            ] == [BASE]


def test_signed_out_is_401_everywhere(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/connections").status_code == 401
    assert put(client).status_code == 401
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 401


def test_the_key_and_address_reach_no_log_line(client: TestClient, sure: FakeSure,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    put(client)
    client.get("/api/connections")
    sure.status = 401
    put(client)
    sure.status = 200
    sure.raw = b"<html>"
    put(client)
    delete_kind(client, "sure", headers=ORIGIN)
    out = capsys.readouterr()
    assert "event=connections" in out.out
    assert KEY not in out.out + out.err and "money.test" not in out.out + out.err


def test_without_the_apps_key_nothing_connects(db_url: str, homes: Homes, sure: FakeSure) -> None:
    for c in app_client(db_url, sure, ""):
        as_(c, homes, "alana")
        listed = ConnectionsResponse.model_validate(c.get("/api/connections").json())
        assert listed.connections == [] and listed.can_connect is False
        assert put(c).status_code == 503
        assert count(db_url) == 0 and sure.seen == []
