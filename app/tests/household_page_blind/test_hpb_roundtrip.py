"""Read-after-write returns what was written; households stay apart; a new household starts empty and neutral."""

from typing import Any

from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from household_page_blind_support import FIELDS, NEUTRAL_DEFAULTS, People, as_, body, fields_of, put, stored
from ashley.people.fields import PROFILE_MAX

ZONES = st.sampled_from(["UTC", "America/Denver", "Europe/Paris", "Asia/Tokyo", "Australia/Sydney", "America/Sao_Paulo"])
LOCALES = st.sampled_from(["en", "en-US", "fr-CA", "de-DE", "pt-BR", "zh-Hant-TW", "ja-JP"])
PROFILES = st.text(alphabet=st.characters(exclude_characters="\x00", exclude_categories=["Cs"]), max_size=300)
LATS = st.floats(-90, 90, allow_nan=False, allow_infinity=False)
LONS = st.floats(-180, 180, allow_nan=False, allow_infinity=False)
PLACES = st.one_of(st.tuples(st.none(), st.none()), st.tuples(LATS, LONS))


@st.composite
def edits(draw: st.DrawFn) -> dict[str, Any]:
    place = draw(PLACES)
    return {"timezone": draw(ZONES), "profile": draw(PROFILES), "locale": draw(LOCALES),
            "unit_system": draw(st.sampled_from(["imperial", "metric"])), "clock": draw(st.sampled_from(["12h", "24h"])),
            "latitude": place[0], "longitude": place[1]}


ONCE = settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])


@ONCE
@given(edit=edits())
def test_what_was_written_is_read_back_exactly(client: TestClient, edit: dict[str, Any]) -> None:
    answered = put(client, edit)
    assert answered.status_code == 200, answered.text
    assert fields_of(answered.json()) == edit
    assert fields_of(stored(client)) == edit


@ONCE
@given(first=edits(), second=edits())
def test_a_write_replaces_every_field_and_the_last_write_wins(client: TestClient, first: dict[str, Any],
                                                              second: dict[str, Any]) -> None:
    assert put(client, first).status_code == 200
    assert put(client, second).status_code == 200
    assert fields_of(stored(client)) == second


@ONCE
@given(edit=edits())
def test_the_same_write_twice_is_the_same_household(client: TestClient, edit: dict[str, Any]) -> None:
    once = put(client, edit).json()
    assert put(client, edit).json() == once


def test_a_write_changes_nothing_the_page_does_not_set(client: TestClient, people: People) -> None:
    before = stored(client)
    after = put(client, body()).json()
    assert (after["id"], after["name"], after["profile_limit"]) == (before["id"], before["name"], before["profile_limit"])
    assert set(after) == set(before)


def test_the_answer_of_a_write_is_the_read_that_follows(client: TestClient) -> None:
    assert put(client, body()).json() == stored(client)


def test_a_refused_write_leaves_the_last_good_one(client: TestClient) -> None:
    good = body(profile="kept")
    assert put(client, good).status_code == 200
    for bad in (body(timezone="Nowhere/Land"), body(locale="x"), body(latitude=95.0), body(longitude=None),
                body(profile="p" * (PROFILE_MAX + 1))):
        assert put(client, bad).status_code == 422
    assert fields_of(stored(client)) == good


def test_the_text_is_kept_as_written(client: TestClient) -> None:
    text = "  Pat & Sam <3 \"cats\"\n\tnew line, ünïcode, 日本語, emoji 🐈  "
    assert put(client, body(profile=text)).json()["profile"] == text
    assert stored(client)["profile"] == text


def test_households_stay_apart(client: TestClient, people: People) -> None:
    as_(client, people, "kim")
    kims = stored(client)
    as_(client, people, "alana")
    assert put(client, body(profile="Alana's house", timezone="Asia/Tokyo")).status_code == 200
    as_(client, people, "kim")
    assert stored(client) == kims
    assert put(client, body(profile="Kim's house", timezone="Pacific/Auckland", latitude=None,
                            longitude=None)).status_code == 200
    as_(client, people, "sam")
    seen = stored(client)
    assert (seen["profile"], seen["timezone"], seen["latitude"]) == ("Alana's house", "Asia/Tokyo", 48.85)
    assert seen["id"] == people.home


def test_the_household_read_is_the_sessions_own_whatever_the_request_names(client: TestClient, people: People) -> None:
    got = client.get("/api/household", params={"id": people.other, "household_id": people.other})
    assert got.json()["id"] == people.home
    got = client.put("/api/household", params={"household_id": people.other}, json=body(profile="mine"),
                     headers={"origin": "https://ashley.test"})
    assert got.json()["id"] == people.home
    as_(client, people, "kim")
    assert stored(client)["profile"] != "mine"


def test_a_new_household_is_empty_and_household_neutral(client: TestClient, people: People) -> None:
    as_(client, people, "kim")
    fresh = stored(client)
    assert {k: fresh[k] for k in NEUTRAL_DEFAULTS} == NEUTRAL_DEFAULTS
    assert fresh["timezone"] == "UTC"
    assert fresh["name"] == "other"
    assert set(FIELDS) <= set(fresh)


def test_the_stored_household_carries_every_wire_field(client: TestClient) -> None:
    assert set(stored(client)) == {"id", "name", "timezone", "profile", "profile_limit", "locale", "unit_system", "clock",
                                   "latitude", "longitude"}


def test_a_profile_with_a_nul_character_is_stored_or_refused_never_a_server_error(client: TestClient) -> None:
    got = put(client, body(profile="a\x00b"))
    assert got.status_code in (200, 422)
