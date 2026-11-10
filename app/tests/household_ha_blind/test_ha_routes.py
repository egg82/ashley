"""Home Assistant as a connection through the real app on a real database and a fake house: checked with `GET /api/`
before it is stored, nothing stored on a refusal, http allowed, the token never on the wire, in a 422 or in a log,
any member may connect, another household never sees or changes it."""

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
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Homes
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from hha_blind_support import CONFIG, FakeHouses, HeldConnections
from connection_routes_support import delete_kind, put_kind

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
URL = "http://ha.test:8123"
TOKEN = "long-lived-token-for-the-test-house"


@dataclass(frozen=True)
class People:
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
def people(db_url: str) -> People:
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return People(alana, sam, {"alana": session(conn, alana, home, "a"), "sam": session(conn, sam, home, "s"),
                                  "kim": session(conn, kim, other, "k")})


@pytest.fixture
def houses() -> FakeHouses:
    return FakeHouses()


def app_client(db_url: str, houses: FakeHouses, key: str) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=key))
    services.register(Homes, ConnectedHomes(HeldConnections(), CONFIG, houses.connect))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c


@pytest.fixture
def client(db_url: str, people: People, houses: FakeHouses) -> Generator[TestClient]:
    for c in app_client(db_url, houses, APP_KEY):
        as_(c, people, "alana")
        yield c


def as_(client: TestClient, people: People, who: str) -> None:
    client.cookies.set(SESSION_COOKIE, people.tokens[who], domain="ashley.test")


def put(client: TestClient, base: str = URL, token: str = TOKEN) -> Response:
    return put_kind(client, "home_assistant", json={"base_url": base, "token": token}, headers=ORIGIN)


def count(db_url: str) -> int:
    return int(scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'home_assistant'"))


def listed(client: TestClient) -> list[HouseholdConnection]:
    return ConnectionsResponse.model_validate(client.get("/api/connections").json()).connections


def test_connecting_returns_the_connection_without_the_token(client: TestClient, people: People, db_url: str) -> None:
    got = put(client)
    assert got.status_code == 200 and TOKEN not in got.text
    made = HouseholdConnection.model_validate(got.json())
    assert made.kind == "home_assistant" and made.base_url == URL
    assert made.added_by is not None and made.added_by.id == people.alana
    assert count(db_url) == 1


def test_http_is_allowed(client: TestClient) -> None:
    assert put(client, "http://ha.willow.home:8123").status_code == 200
    assert put(client, "https://ha.example.test").status_code == 200


def test_it_is_checked_against_the_greeting_with_the_token_before_it_is_stored(client: TestClient,
                                                                               houses: FakeHouses) -> None:
    put(client)
    assert houses.seen
    assert {(h, m, p, b) for h, m, p, b in houses.seen} == {("ha.test:8123", "GET", "/api/", f"Bearer {TOKEN}")}


@pytest.mark.parametrize(("mode", "reason"), [("refuse", "key_refused"), ("down", "unreachable"),
                                              ("stranger", "wrong_service")])
def test_each_refusal_is_typed_and_stores_nothing(client: TestClient, houses: FakeHouses, db_url: str, mode: str,
                                                  reason: str) -> None:
    if mode == "refuse":
        houses.refuse.add("ha.test")
    elif mode == "down":
        houses.down.add("ha.test")
    else:
        houses.greeting = {"something": "else"}
    got = put(client)
    assert got.status_code == 400
    assert ConnectionRefused.model_validate(got.json()).reason == reason
    assert TOKEN not in got.text
    assert count(db_url) == 0


@pytest.mark.parametrize("base", ["ha.test", "ftp://ha.test", "http://", "http://u:p@ha.test",
                                  "http://ha.test/?a=1", "http://ha.test/#x"])
def test_a_bad_address_is_bad_url_and_asks_the_house_nothing(client: TestClient, houses: FakeHouses, db_url: str,
                                                             base: str) -> None:
    got = put(client, base)
    assert got.status_code == 400 and ConnectionRefused.model_validate(got.json()).reason == "bad_url"
    assert houses.seen == [] and count(db_url) == 0


def test_a_refused_replacement_leaves_the_old_connection(client: TestClient, houses: FakeHouses, db_url: str) -> None:
    assert put(client).status_code == 200
    before = bytes(scalar(db_url, "SELECT secret FROM connections WHERE kind = 'home_assistant'"))
    houses.refuse.add("new.test")
    assert put(client, "http://new.test", "other-token").status_code == 400
    assert bytes(scalar(db_url, "SELECT secret FROM connections WHERE kind = 'home_assistant'")) == before
    assert [c.base_url for c in listed(client)] == [URL]


def test_the_stored_secret_is_sealed_and_never_the_token(client: TestClient, db_url: str) -> None:
    put(client)
    stored = bytes(scalar(db_url, "SELECT secret FROM connections WHERE kind = 'home_assistant'"))
    assert stored and TOKEN.encode() not in stored and base64.b64encode(TOKEN.encode()) not in stored


def test_any_member_sees_replaces_and_removes_it(client: TestClient, people: People, db_url: str) -> None:
    assert put(client).status_code == 200
    as_(client, people, "sam")
    assert [c.base_url for c in listed(client)] == [URL]
    replaced = put(client, "http://ha2.test:8123", "newer-token")
    assert replaced.status_code == 200 and "newer-token" not in replaced.text
    assert [(c.base_url, c.added_by.id if c.added_by else None) for c in listed(client)] == [
        ("http://ha2.test:8123", people.sam)]
    assert count(db_url) == 1
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 204
    assert count(db_url) == 0 and listed(client) == []
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 404


def test_the_token_is_on_no_read_back(client: TestClient) -> None:
    put(client)
    for got in (client.get("/api/connections"), put(client)):
        body = got.json()
        shown = str(body["connections"] if "connections" in body else body)
        assert TOKEN not in got.text and "token" not in shown


def test_removing_home_assistant_leaves_a_sure_connection(client: TestClient, people: People, db_url: str) -> None:
    put(client)
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE connections SET kind = 'sure'")
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 404
    assert int(scalar(db_url, "SELECT count(*) FROM connections")) == 1


def test_another_household_sees_nothing_and_cannot_remove(client: TestClient, people: People, db_url: str) -> None:
    put(client)
    as_(client, people, "kim")
    assert listed(client) == []
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 404
    assert count(db_url) == 1


def test_each_household_holds_its_own_house(client: TestClient, people: People, db_url: str) -> None:
    put(client)
    as_(client, people, "kim")
    assert put(client, "http://kims.test:8123", "kims-token").status_code == 200
    assert count(db_url) == 2
    assert [c.base_url for c in listed(client)] == ["http://kims.test:8123"]
    as_(client, people, "alana")
    assert [c.base_url for c in listed(client)] == [URL]


def test_signed_out_is_401_everywhere(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/connections").status_code == 401
    assert put(client).status_code == 401
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 401


@pytest.mark.parametrize("body", [{"token": TOKEN}, {"base_url": 5, "token": TOKEN}, {"base_url": URL, "token": ["x"]}])
def test_a_rejected_body_does_not_echo_the_token(client: TestClient, db_url: str, body: dict[str, object]) -> None:
    got = put_kind(client, "home_assistant", json=body, headers=ORIGIN)
    assert got.status_code in (400, 422)
    assert TOKEN not in got.text
    assert count(db_url) == 0


def test_a_wrongly_typed_token_value_is_not_echoed(client: TestClient) -> None:
    secret = "typed-wrong-secret-value"
    got = put_kind(client, "home_assistant", json={"base_url": 42, "token": secret}, headers=ORIGIN)
    assert got.status_code == 422 and secret not in got.text


def test_the_token_and_address_reach_no_log_line(client: TestClient, houses: FakeHouses,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    put(client)
    client.get("/api/connections")
    houses.refuse.add("ha.test")
    put(client)
    houses.refuse.clear()
    houses.greeting = {"x": 1}
    put(client)
    put_kind(client, "home_assistant", json={"token": TOKEN}, headers=ORIGIN)
    delete_kind(client, "home_assistant", headers=ORIGIN)
    out = capsys.readouterr()
    assert "event=connections" in out.out
    assert TOKEN not in out.out + out.err and "ha.test" not in out.out + out.err


def test_without_the_apps_key_nothing_connects(db_url: str, people: People, houses: FakeHouses) -> None:
    for c in app_client(db_url, houses, ""):
        as_(c, people, "alana")
        got = ConnectionsResponse.model_validate(c.get("/api/connections").json())
        assert got.connections == [] and got.can_connect is False
        assert put(c).status_code == 503
        assert count(db_url) == 0 and houses.seen == []
