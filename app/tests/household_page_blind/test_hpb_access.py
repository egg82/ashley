"""Who may read and write the household page: a signed-in person of the household, over the site's own origin."""

import pytest
from fastapi.testclient import TestClient
from household_page_blind_support import ORIGIN, People, as_, body, get, put, stored


def test_signed_out_is_401_on_read_and_write(client: TestClient, people: People) -> None:
    as_(client, people, None)
    assert get(client).status_code == 401
    assert put(client, body()).status_code == 401


def test_an_unknown_session_token_is_401(client: TestClient) -> None:
    client.cookies.clear()
    client.cookies.set("__Host-ashley_session", "not-a-live-token", domain="ashley.test")
    assert get(client).status_code == 401
    assert put(client, body()).status_code == 401


def test_a_refused_write_stores_nothing(client: TestClient, people: People) -> None:
    before = stored(client)
    as_(client, people, None)
    assert put(client, body(profile="signed out")).status_code == 401
    as_(client, people, "alana")
    assert stored(client) == before


@pytest.mark.parametrize("who", ["alana", "sam", "kim"])
def test_every_person_of_a_household_reads_it(client: TestClient, people: People, who: str) -> None:
    as_(client, people, who)
    got = get(client)
    assert got.status_code == 200
    assert got.json()["id"] == (people.other if who == "kim" else people.home)


@pytest.mark.parametrize("who", ["alana", "sam"])
def test_any_person_of_the_household_may_write_it(client: TestClient, people: People, who: str) -> None:
    as_(client, people, who)
    assert put(client, body(profile=f"set by {who}")).status_code == 200
    as_(client, people, "alana")
    assert stored(client)["profile"] == f"set by {who}"


def test_the_name_is_read_here_and_never_set_here(client: TestClient) -> None:
    before = stored(client)
    got = put(client, {**body(), "name": "renamed"})
    assert got.status_code == 422
    assert stored(client) == before
    assert put(client, body()).json()["name"] == before["name"]


def test_a_write_from_another_site_is_403_and_stores_nothing(client: TestClient) -> None:
    before = stored(client)
    assert put(client, body(profile="forged"), {"origin": "https://evil.example"}).status_code == 403
    assert stored(client) == before


def test_the_site_own_origin_is_accepted(client: TestClient) -> None:
    assert put(client, body(), ORIGIN).status_code == 200


def test_a_read_needs_no_origin(client: TestClient) -> None:
    assert get(client).status_code == 200
