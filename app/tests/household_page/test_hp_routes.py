"""`GET|PUT /api/household`: a signed-in person reads and sets their own household's timezone, profile, locale, unit
system and clock; no route reaches another household's; a value she cannot use is refused with nothing stored; and
what is set is what People hands the persona."""

from collections.abc import Generator

import pytest
from ashley.db.pool import PoolDatabase
from ashley.people.fields import PROFILE_MAX
from ashley.people.postgres import PostgresPeople
from ashley.persona import facts
from contract.conversations_support import run
from fastapi.testclient import TestClient
from household_page_support import BASE, METRIC, People, app_client, as_, people_in, put, stored

DEFAULTS = ("America/Denver", "", "en-US", "imperial", "24h")


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    with app_client(db_url) as c:
        as_(c, people, "alana")
        yield c


def test_a_new_household_reads_what_the_code_assumed(client: TestClient, people: People) -> None:
    got = client.get(BASE)
    assert got.status_code == 200, got.text
    assert got.json() == {"id": people.home, "name": "home", "timezone": "America/Denver", "profile": "",
                          "profile_limit": PROFILE_MAX, "locale": "en-US", "unit_system": "imperial", "clock": "24h"}


def test_what_is_put_is_stored_and_read_back(client: TestClient, people: People, db_url: str) -> None:
    got = put(client, METRIC)
    assert got.status_code == 200, got.text
    assert {k: got.json()[k] for k in METRIC} == METRIC
    assert client.get(BASE).json() == got.json()
    assert stored(db_url, people.home) == tuple(METRIC.values())


def test_any_person_of_the_household_sets_it_and_another_household_is_untouched(client: TestClient, people: People,
                                                                                db_url: str) -> None:
    as_(client, people, "sam")
    assert put(client, METRIC).status_code == 200
    as_(client, people, "kim")
    assert client.get(BASE).json()["id"] == people.other
    assert put(client, {**METRIC, "timezone": "Asia/Tokyo"}).json()["id"] == people.other
    assert stored(db_url, people.home) == tuple(METRIC.values())
    assert stored(db_url, people.other)[0] == "Asia/Tokyo"


@pytest.mark.parametrize(("field", "value"), [
    ("timezone", "Mars/Olympus"), ("timezone", ""), ("timezone", "../etc/passwd"),
    ("locale", "english"), ("locale", "EN-us"), ("locale", "en_US"), ("locale", "")])
def test_a_timezone_or_locale_she_cannot_use_is_refused_by_name(client: TestClient, people: People, db_url: str,
                                                                field: str, value: str) -> None:
    got = put(client, {**METRIC, field: value})
    assert got.status_code == 422, got.text
    assert got.json()["invalid"] == field
    assert stored(db_url, people.home) == DEFAULTS


@pytest.mark.parametrize("body", [
    {**METRIC, "unit_system": "kelvin"}, {**METRIC, "clock": "13h"}, {**METRIC, "profile": "x" * (PROFILE_MAX + 1)},
    {k: v for k, v in METRIC.items() if k != "clock"}, {**METRIC, "name": "renamed"}])
def test_a_body_outside_the_schema_is_422_and_stores_nothing(client: TestClient, people: People, db_url: str,
                                                            body: dict[str, str]) -> None:
    got = put(client, body)
    assert got.status_code == 422, got.text
    assert "invalid" not in got.json()
    assert stored(db_url, people.home) == DEFAULTS


def test_no_session_reads_or_writes_nothing(client: TestClient, people: People, db_url: str) -> None:
    as_(client, people, None)
    assert client.get(BASE).status_code == 401
    assert put(client, METRIC).status_code == 401
    assert stored(db_url, people.home) == DEFAULTS


def test_a_write_from_another_site_is_403(client: TestClient, people: People, db_url: str) -> None:
    assert client.put(BASE, json=METRIC, headers={"origin": "https://evil.test"}).status_code == 403
    assert stored(db_url, people.home) == DEFAULTS


def test_the_write_logs_which_fields_changed_never_their_values(client: TestClient,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    put(client, {"timezone": "America/Denver", "profile": "Mochi the cat.", "locale": "en-US",
                 "unit_system": "metric", "clock": "24h"})
    out = capsys.readouterr().out
    [line] = [x for x in out.splitlines() if "people.household.changed" in x]
    assert "changed=profile,unit_system" in line and "fields=2" in line
    assert "Mochi" not in out and "metric" not in out


def test_what_is_set_is_what_the_persona_hears(client: TestClient, people: People, db_url: str) -> None:
    put(client, METRIC)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            household = await PostgresPeople(database).household(people.home)
        finally:
            await database.close()
        assert household is not None
        assert facts.profile(household) == ("# This household\n\n" + facts.UNITS["metric"] + "\n\n"
                                            + METRIC["profile"])

    run(scenario())
