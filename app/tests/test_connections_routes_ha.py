"""A household's Home Assistant connection end to end through the real app, a real database and a stand-in HA: a
person connects it with an address (http allowed, as a household's own HA usually is) and a token checked with one
`GET /api/`, another of the household sees, replaces and removes it, beside the household's Sure; what HA does not pass
stores nothing; the token is never on the wire back, in a 422, nor in a log line; another household sees none of it.
A turn's house is then the household's own (`home_assistant.homes.Homes`)."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import logs, services
from ashley.api.connection_models import ConnectionRefused, HouseholdConnection
from ashley.connections.connections import Connections
from ashley.home_assistant.connected_homes import ConnectedHomes
from ashley.home_assistant.homes import Homes
from ashley.main import create_app
from ashley.settings import Settings
from ashley.sure.client import Sure
from automations_support import CONFIG
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from homes_support import TOKEN, StandIn
from money_support import FakeSure
from test_connections_routes import APP_KEY, ORIGIN, PUBLIC, Homes as People, as_, homes as homes, listed
from test_connections_routes import connect as connect_sure
from connection_routes_support import delete_kind, put_kind

HA = "http://ha.house.test:8123"


@pytest.fixture
def stand() -> StandIn:
    return StandIn()


@pytest.fixture
def client(db_url: str, homes: People, stand: StandIn) -> Generator[TestClient]:
    services.unregister(Connections)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    services.register(Sure, FakeSure().client())
    services.register(Homes, ConnectedHomes(services.get(Connections), CONFIG, stand.connect))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        as_(c, homes.alana_token)
        yield c
    for interface in (Sure, Connections, Homes):
        services.unregister(interface)


def connect(client: TestClient, base: str = HA, token: str = TOKEN) -> HouseholdConnection | ConnectionRefused:
    got = put_kind(client, "home_assistant", json={"base_url": base, "token": token}, headers=ORIGIN)
    assert token not in got.text
    if got.status_code == 400:
        return ConnectionRefused.model_validate(got.json())
    assert got.status_code == 200, got.text
    return HouseholdConnection.model_validate(got.json())


def test_a_person_connects_the_households_home_assistant_and_another_replaces_and_removes_it(
        client: TestClient, homes: People, stand: StandIn, db_url: str) -> None:
    made = connect(client, HA + "/")
    assert isinstance(made, HouseholdConnection) and made.kind == "home_assistant" and made.base_url == HA
    assert made.added_by is not None and made.added_by.id == homes.alana
    assert stand.seen == [(HA, "/api/", TOKEN)]
    assert isinstance(connect_sure(client), HouseholdConnection)
    as_(client, homes.sam_token)
    assert [c.kind for c in listed(client).connections] == ["home_assistant", "sure"]
    stand.token = "a-newer-token"
    again = connect(client, token="a-newer-token")
    assert isinstance(again, HouseholdConnection) and again.added_by is not None and again.added_by.id == homes.sam
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 204
    assert [c.kind for c in listed(client).connections] == ["sure"]
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 404
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE kind = 'home_assistant'") == 0


def test_a_turns_house_is_the_households_own(client: TestClient, homes: People, stand: StandIn, db_url: str) -> None:
    connect(client)
    household = scalar(db_url, f"SELECT household_id FROM people WHERE id = {homes.alana}")
    other = scalar(db_url, f"SELECT household_id FROM people WHERE id <> {homes.alana} AND id <> {homes.sam}")

    async def scenario() -> None:
        home = await services.get(Homes).of(household)
        assert home is not None and str(home.home_assistant.http.base_url).startswith(HA)
        assert await services.get(Homes).of(other) is None

    asyncio.run(scenario())


def test_another_household_sees_none_of_it(client: TestClient, homes: People) -> None:
    connect(client)
    as_(client, homes.kim_token)
    assert listed(client).connections == []
    assert delete_kind(client, "home_assistant", headers=ORIGIN).status_code == 404


@pytest.mark.parametrize(("base", "status", "raw", "reason"), [
    ("ftp://ha.test", None, None, "bad_url"), ("http://", None, None, "bad_url"),
    ("http://user:pw@ha.test", None, None, "bad_url"), ("http://ha.test/?x=1", None, None, "bad_url"),
    (HA, 401, None, "key_refused"), (HA, 302, None, "unreachable"), (HA, 502, None, "unreachable"),
    (HA, 404, None, "wrong_service"), (HA, 200, b"<html>sign in</html>", "wrong_service")])
def test_a_connection_home_assistant_does_not_pass_stores_nothing(
        client: TestClient, stand: StandIn, db_url: str, base: str, status: int | None, raw: bytes | None,
        reason: str) -> None:
    stand.status, stand.raw = status, raw
    got = connect(client, base)
    assert isinstance(got, ConnectionRefused) and got.reason == reason
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0
    if reason == "bad_url":
        assert stand.seen == []


def test_a_malformed_body_does_not_echo_the_token_back(client: TestClient) -> None:
    missing = put_kind(client, "home_assistant", json={"token": TOKEN}, headers=ORIGIN)
    spaced = put_kind(client, "home_assistant", json={"base_url": HA, "token": f"{TOKEN} {TOKEN}"}, headers=ORIGIN)
    long = put_kind(client, "home_assistant", json={"base_url": HA, "token": TOKEN + "x" * 4000}, headers=ORIGIN)
    assert missing.status_code == 400 and missing.json()["reason"] == "bad_url" and TOKEN not in missing.text
    for got in (spaced, long):
        assert got.status_code == 422 and TOKEN not in got.text


def test_a_write_from_another_site_is_refused(client: TestClient, stand: StandIn) -> None:
    assert put_kind(client, "home_assistant", json={"base_url": HA, "token": TOKEN},
                      headers={"origin": "https://evil.test"}).status_code == 403
    assert delete_kind(client, "home_assistant", headers={"origin": "https://evil.test"}).status_code == 403
    assert stand.seen == []


def test_the_token_and_address_reach_no_log_line(client: TestClient, stand: StandIn,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    connect(client)
    stand.status = 401
    connect(client)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert any("event=connections.connected" in ln and "kind=home_assistant" in ln for ln in lines)
    assert any("event=connections.refused" in ln and "kind=home_assistant" in ln for ln in lines)
    assert not any(TOKEN in ln or "house.test" in ln for ln in lines)
