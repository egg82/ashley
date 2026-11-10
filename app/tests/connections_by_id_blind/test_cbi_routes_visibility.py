"""Who can reach a connection over HTTP: a household's connection any member, a personal one only its owner, another
household's nobody; what a person cannot see is 404 (never 403) and untouched."""

import pytest
from connections_by_id_blind_support import ORIGIN, URL, Checks, People, as_, rows, snapshot
from fastapi.testclient import TestClient
from httpx2 import Response

SECRET = "route-secret-0001"


def made(client: TestClient, kind: str, label: str = "a") -> int:
    got = client.post("/api/connections", json={"kind": kind, "label": label, "base_url": URL, "token": SECRET},
                      headers=ORIGIN)
    assert got.status_code == 201
    return int(got.json()["id"])


def ids(client: TestClient) -> list[int]:
    return [c["id"] for c in client.get("/api/connections").json()["connections"]]


def each_write(client: TestClient, i: int) -> list[Response]:
    return [client.put(f"/api/connections/{i}", json={"base_url": URL, "token": "intruder-0002"}, headers=ORIGIN),
            client.patch(f"/api/connections/{i}", json={"label": "intruder"}, headers=ORIGIN),
            client.delete(f"/api/connections/{i}", headers=ORIGIN)]


def test_a_household_connection_is_listed_and_changed_by_every_member(client: TestClient, people: People) -> None:
    i = made(client, "multi")
    as_(client, people, "sam")
    assert ids(client) == [i]
    puts = client.put(f"/api/connections/{i}", json={"base_url": URL, "token": "sams-0002"}, headers=ORIGIN)
    assert puts.status_code == 200
    assert client.patch(f"/api/connections/{i}", json={"label": "sams"}, headers=ORIGIN).status_code == 200
    assert client.delete(f"/api/connections/{i}", headers=ORIGIN).status_code == 204


def test_a_personal_connection_is_listed_to_its_owner_alone(client: TestClient, people: People) -> None:
    i = made(client, "own")
    assert ids(client) == [i]
    as_(client, people, "sam")
    assert ids(client) == []
    as_(client, people, "kim")
    assert ids(client) == []


@pytest.mark.parametrize("who", ["sam", "kim"])
def test_a_personal_connection_is_404_to_anyone_else_and_untouched(client: TestClient, people: People, db_url: str,
                                                                   checks: Checks, who: str) -> None:
    i = made(client, "own")
    before = snapshot(db_url)
    checks.given.clear()
    as_(client, people, who)
    for got in each_write(client, i):
        assert got.status_code == 404 and got.json()["code"] == "not_found"
    assert snapshot(db_url) == before and checks.given == []


def test_another_households_connection_is_404_and_untouched(client: TestClient, people: People, db_url: str) -> None:
    as_(client, people, "kim")
    i = made(client, "multi")
    before = snapshot(db_url)
    as_(client, people, "alana")
    assert ids(client) == []
    for got in each_write(client, i):
        assert got.status_code == 404
    assert snapshot(db_url) == before


def test_each_household_holds_its_own_limit_over_http(client: TestClient, people: People) -> None:
    for label in ("a", "b", "c"):
        made(client, "multi", label)
    as_(client, people, "kim")
    for label in ("a", "b", "c"):
        made(client, "multi", label)
    assert rows(people.url) == 6
