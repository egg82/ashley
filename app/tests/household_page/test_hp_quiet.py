"""`GET|PUT /api/household/quiet`: a person reads and sets only their own quiet hours, a window she cannot use is refused with
nothing stored, clearing it stores none, and what is set is what People hands the readers of a person."""

import asyncio
import logging
from collections.abc import Generator
from datetime import UTC, datetime

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.people.model import QuietHours
from ashley.people.postgres import PostgresPeople
from ashley.people.quiet import holds
from fastapi.testclient import TestClient
from household_page_support import ORIGIN, People, app_client, as_, people_in
from household_routes_support import events

URL = "/api/household/quiet"
NIGHT = {"start": 22, "end": 7, "timezone": "Europe/London"}


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    with app_client(db_url) as c:
        as_(c, people, "alana")
        yield c


def put(client: TestClient, quiet: object) -> int:
    return client.put(URL, json={"quiet": quiet}, headers=ORIGIN).status_code


def row(db_url: str, person: int) -> tuple[object, ...]:
    with psycopg.connect(db_url) as conn:
        got = conn.execute("SELECT quiet_from, quiet_to, quiet_timezone FROM people WHERE id = %s", (person,)).fetchone()
    assert got is not None
    return got


def test_a_person_starts_with_none_and_what_they_set_is_read_back_and_stored(client: TestClient, people: People,
                                                                              db_url: str) -> None:
    assert client.get(URL).json() == {"quiet": None}
    assert put(client, NIGHT) == 200
    assert client.get(URL).json() == {"quiet": NIGHT}
    assert row(db_url, people.alana) == (22, 7, "Europe/London")


def test_it_is_their_own_and_no_other_persons_or_households(client: TestClient, people: People, db_url: str) -> None:
    assert put(client, NIGHT) == 200
    as_(client, people, "sam")
    assert client.get(URL).json() == {"quiet": None}
    as_(client, people, "kim")
    assert put(client, {**NIGHT, "timezone": "Asia/Tokyo"}) == 200
    assert row(db_url, people.alana) == (22, 7, "Europe/London") and row(db_url, people.sam) == (None, None, None)
    assert row(db_url, people.kim) == (22, 7, "Asia/Tokyo")


def test_null_clears_them(client: TestClient, people: People, db_url: str) -> None:
    put(client, NIGHT)
    assert put(client, None) == 200
    assert client.get(URL).json() == {"quiet": None} and row(db_url, people.alana) == (None, None, None)


@pytest.mark.parametrize(("body", "invalid"), [
    ({"start": 9, "end": 9, "timezone": "UTC"}, "hours"),
    ({"start": 22, "end": 7, "timezone": "Mars/Olympus"}, "timezone"),
    ({"start": 22, "end": 7, "timezone": ""}, "timezone"),
    ({"start": 22, "end": 7, "timezone": "../etc/passwd"}, "timezone")])
def test_a_window_she_cannot_use_is_refused_and_nothing_is_stored(client: TestClient, people: People, db_url: str,
                                                                  body: dict[str, object], invalid: str) -> None:
    put(client, NIGHT)
    got = client.put(URL, json={"quiet": body}, headers=ORIGIN)
    assert got.status_code == 422 and got.json()["invalid"] == invalid
    assert row(db_url, people.alana) == (22, 7, "Europe/London")


@pytest.mark.parametrize("hour", [-1, 24])
def test_an_hour_outside_the_day_is_not_a_window(client: TestClient, hour: int) -> None:
    assert put(client, {**NIGHT, "start": hour}) == 422


def test_the_write_needs_a_session_and_comes_from_this_site(client: TestClient, people: People) -> None:
    assert client.put(URL, json={"quiet": NIGHT}, headers={"origin": "https://evil.test"}).status_code == 403
    as_(client, people, None)
    assert client.get(URL).status_code == 401 and put(client, NIGHT) == 401


def test_the_write_is_logged_with_ids_never_the_window(client: TestClient, people: People,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.people")
    put(client, NIGHT)
    put(client, None)
    assert events(caplog, "people.quiet.changed") == [
        {"household": people.home, "person": people.alana, "set": True},
        {"household": people.home, "person": people.alana, "set": False}]


def test_people_hands_back_the_hours_that_were_set(client: TestClient, people: People, db_url: str) -> None:
    put(client, NIGHT)

    async def work() -> tuple[QuietHours | None, QuietHours | None]:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            household = await PostgresPeople(database).household(people.home)
        finally:
            await database.close()
        assert household is not None
        by = {p.id: p.quiet for p in household.people}
        return by[people.alana], by[people.sam]
    mine, theirs = asyncio.run(work())
    assert mine == QuietHours(22, 7, "Europe/London") and theirs is None
    assert holds(mine, datetime(2026, 1, 15, 23, 30, tzinfo=UTC)) is True


def test_the_database_refuses_a_half_set_window(db_url: str, people: People) -> None:
    with psycopg.connect(db_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE people SET quiet_from = 1 WHERE id = %s", (people.alana,))
    with psycopg.connect(db_url) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE people SET quiet_from = 5, quiet_to = 5, quiet_timezone = 'UTC' WHERE id = %s",
                     (people.alana,))
