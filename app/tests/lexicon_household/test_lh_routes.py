"""`GET /api/lexicon`, `PUT|DELETE /api/lexicon/{real}`: each household has its own words, any of its people may edit
them, no route reaches another household's, and a word she cannot store is refused with nothing stored."""

from collections.abc import Generator

import pytest
from ashley.channels.lexicons import MAX_ENTRIES
from fastapi.testclient import TestClient
from lexicon_household_support import (BASE, People, app_client, as_, count_in, delete, listed, people_in, put)
import psycopg


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    with app_client(db_url) as c:
        as_(c, people, "alana")
        yield c


def test_a_household_starts_with_no_words(client: TestClient) -> None:
    got = client.get(BASE)
    assert got.status_code == 200
    assert got.json()["words"] == [] and got.json()["limit"] == MAX_ENTRIES


def test_a_word_put_is_read_back_with_who_set_it(client: TestClient, people: People) -> None:
    put_ = put(client, "Mochi", "Mowchi")
    assert put_.status_code == 200, put_.text
    assert put_.json()["real"] == "Mochi" and put_.json()["spoken"] == "Mowchi"
    assert put_.json()["edited_by"]["id"] == people.alana
    assert listed(client) == {"Mochi": "Mowchi"}
    assert put(client, "Mochi", "Moe-chee").status_code == 200
    assert listed(client) == {"Mochi": "Moe-chee"}


def test_two_households_hold_their_own_words(client: TestClient, people: People) -> None:
    put(client, "Mochi", "Mowchi")
    as_(client, people, "kim")
    assert listed(client) == {}
    assert put(client, "Mochi", "Moe-chee").status_code == 200
    assert put(client, "Nuuk", "Nook").status_code == 200
    assert listed(client) == {"Nuuk": "Nook", "Mochi": "Moe-chee"}
    as_(client, people, "alana")
    assert listed(client) == {"Mochi": "Mowchi"}


def test_any_person_of_the_household_edits_its_words(client: TestClient, people: People) -> None:
    put(client, "Mochi", "Mowchi")
    as_(client, people, "sam")
    assert listed(client) == {"Mochi": "Mowchi"}
    assert put(client, "Nuuk", "Nook").json()["edited_by"]["id"] == people.sam
    assert delete(client, "Mochi").status_code == 204
    as_(client, people, "alana")
    assert listed(client) == {"Nuuk": "Nook"}


def test_another_household_cannot_remove_or_replace_a_word(client: TestClient, people: People, db_url: str) -> None:
    put(client, "Mochi", "Mowchi")
    as_(client, people, "kim")
    gone = delete(client, "Mochi")
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"
    put(client, "Mochi", "Other")
    as_(client, people, "alana")
    assert listed(client) == {"Mochi": "Mowchi"}
    assert count_in(db_url, people.home) == 1


def test_a_removed_word_is_gone_and_removing_it_again_is_404(client: TestClient) -> None:
    put(client, "Mochi", "Mowchi")
    assert delete(client, "Mochi").status_code == 204
    assert listed(client) == {}
    assert delete(client, "Mochi").status_code == 404


@pytest.mark.parametrize(("real", "spoken", "reason"), [
    ("two%20words", "x", "not_a_word"), ("%20", "x", "not_a_word"), ("Mochi", "%20", "blank_spelling"),
    ("S" * 65, "x", "too_long"), ("Mochi", "x" * 65, "too_long")])
def test_a_word_she_cannot_store_is_422_and_stores_nothing(client: TestClient, db_url: str, people: People,
                                                           real: str, spoken: str, reason: str) -> None:
    got = put(client, real, spoken.replace("%20", " "))
    assert got.status_code == 422, got.text
    assert got.json()["refused_for"] == reason
    assert count_in(db_url, people.home) == 0


def test_a_household_at_the_limit_may_replace_but_not_add(client: TestClient, db_url: str, people: People) -> None:
    with psycopg.connect(db_url) as conn:
        conn.execute("INSERT INTO household_lexicon (household_id, real, spoken, updated_at) "
                     "SELECT %s, 'w' || i, 'x', now() FROM generate_series(0, %s) AS i", (people.home, MAX_ENTRIES - 1))
    full = put(client, "Mochi", "Mowchi")
    assert full.status_code == 422 and full.json()["refused_for"] == "full"
    assert put(client, "w0", "changed").status_code == 200
    assert count_in(db_url, people.home) == MAX_ENTRIES
    as_(client, people, "kim")
    assert put(client, "Mochi", "Mowchi").status_code == 200


def test_no_session_reads_or_writes_nothing(client: TestClient, people: People, db_url: str) -> None:
    as_(client, people, None)
    assert client.get(BASE).status_code == 401
    assert put(client, "Mochi", "Mowchi").status_code == 401
    assert delete(client, "Mochi").status_code == 401
    assert count_in(db_url, people.home) == 0


def test_an_edit_from_another_site_is_403(client: TestClient, db_url: str, people: People) -> None:
    foreign = {"origin": "https://evil.test"}
    assert client.put(f"{BASE}/Mochi", json={"spoken": "x"}, headers=foreign).status_code == 403
    assert client.delete(f"{BASE}/Mochi", headers=foreign).status_code == 403
    assert count_in(db_url, people.home) == 0
