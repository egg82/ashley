"""Each field's validation: what is refused is refused whole, with the named reason, and stores nothing."""

import json
from typing import Any

import pytest
from ashley.people.fields import PROFILE_MAX
from fastapi.testclient import TestClient
from household_page_blind_support import body, put, stored

BAD_ZONES = ["", "Mars/Olympus_Mons", "not a zone", "America/Denver ", "denverish", "UTC+99", "America/", "/"]
GOOD_ZONES = ["UTC", "America/Denver", "Europe/Paris", "Asia/Kolkata", "Pacific/Auckland", "America/Argentina/Buenos_Aires"]
BAD_LOCALES = ["", "e", "en_US", "english", "en-", "-US", "en US", "12", "en-USAA", "en--US", "en-US-", "!!", "en-U"]
GOOD_LOCALES = ["en", "en-US", "fr-CA", "de-DE", "pt-BR", "zh-Hant", "zh-Hant-TW", "sr-Latn-RS", "ja-JP"]


def assert_refused_whole(client: TestClient, payload: dict[str, Any], before: dict[str, Any], invalid: str | None) -> None:
    got = put(client, payload)
    assert got.status_code == 422, got.text
    if invalid is not None:
        assert got.json()["invalid"] == invalid
        assert isinstance(got.json()["detail"], str)
    assert stored(client) == before


@pytest.mark.parametrize("zone", BAD_ZONES)
def test_a_timezone_that_is_not_an_iana_zone_is_refused_as_timezone(client: TestClient, zone: str) -> None:
    assert_refused_whole(client, body(timezone=zone), stored(client), "timezone")


@pytest.mark.parametrize("zone", GOOD_ZONES)
def test_an_iana_zone_is_accepted_and_kept(client: TestClient, zone: str) -> None:
    assert put(client, body(timezone=zone)).json()["timezone"] == zone
    assert stored(client)["timezone"] == zone


def test_a_timezone_past_its_limit_is_refused(client: TestClient) -> None:
    assert_refused_whole(client, body(timezone="America/" + "x" * 64), stored(client), None)


@pytest.mark.parametrize("locale", BAD_LOCALES)
def test_a_locale_that_is_not_a_bcp47_tag_is_refused_as_locale(client: TestClient, locale: str) -> None:
    assert_refused_whole(client, body(locale=locale), stored(client), "locale")


@pytest.mark.parametrize("locale", GOOD_LOCALES)
def test_a_bcp47_tag_of_language_script_and_region_is_accepted(client: TestClient, locale: str) -> None:
    assert put(client, body(locale=locale)).json()["locale"] == locale
    assert stored(client)["locale"] == locale


def test_a_locale_past_its_limit_is_refused(client: TestClient) -> None:
    assert_refused_whole(client, body(locale="en-" + "x" * 33), stored(client), None)


@pytest.mark.parametrize("clock", ["", "am", "12", "24", "12H", "24 h", "twelve", None, 12])
def test_a_clock_outside_the_enum_is_refused(client: TestClient, clock: Any) -> None:
    assert_refused_whole(client, body(clock=clock), stored(client), None)


@pytest.mark.parametrize("units", ["", "si", "Metric", "IMPERIAL", "us", None, 1])
def test_a_unit_system_outside_the_enum_is_refused(client: TestClient, units: Any) -> None:
    assert_refused_whole(client, body(unit_system=units), stored(client), None)


@pytest.mark.parametrize("clock", ["12h", "24h"])
@pytest.mark.parametrize("units", ["imperial", "metric"])
def test_every_enum_value_is_accepted(client: TestClient, clock: str, units: str) -> None:
    got = put(client, body(clock=clock, unit_system=units))
    assert (got.status_code, got.json()["clock"], got.json()["unit_system"]) == (200, clock, units)


def test_the_profile_limit_is_stated_and_a_profile_at_it_is_kept(client: TestClient) -> None:
    limit = stored(client)["profile_limit"]
    assert limit == PROFILE_MAX
    full = "p" * limit
    assert put(client, body(profile=full)).json()["profile"] == full
    assert stored(client)["profile"] == full


def test_a_profile_over_its_limit_is_refused_and_the_old_one_stays(client: TestClient) -> None:
    assert put(client, body(profile="before")).status_code == 200
    assert_refused_whole(client, body(profile="p" * (PROFILE_MAX + 1)), stored(client), None)
    assert stored(client)["profile"] == "before"


def test_the_profile_limit_counts_characters_not_bytes(client: TestClient) -> None:
    text = "é" * PROFILE_MAX
    assert put(client, body(profile=text)).json()["profile"] == text


def test_an_empty_profile_is_allowed_and_is_empty_prose_not_null(client: TestClient) -> None:
    assert put(client, body(profile="something")).status_code == 200
    assert put(client, body(profile="")).json()["profile"] == ""
    assert stored(client)["profile"] == ""


@pytest.mark.parametrize("latitude", [90.0001, -90.0001, 91, -91, 1000])
def test_a_latitude_outside_range_is_refused(client: TestClient, latitude: float) -> None:
    assert_refused_whole(client, body(latitude=latitude), stored(client), None)


@pytest.mark.parametrize("longitude", [180.0001, -180.0001, 181, -181, 1000])
def test_a_longitude_outside_range_is_refused(client: TestClient, longitude: float) -> None:
    assert_refused_whole(client, body(longitude=longitude), stored(client), None)


@pytest.mark.parametrize("lat,lon", [(90, 180), (-90, -180), (0, 0), (-0.5, 0.5)])
def test_the_limits_of_the_range_are_accepted(client: TestClient, lat: float, lon: float) -> None:
    got = put(client, body(latitude=lat, longitude=lon))
    assert (got.status_code, got.json()["latitude"], got.json()["longitude"]) == (200, lat, lon)


@pytest.mark.parametrize("pair", [(48.85, None), (None, 2.35), (0.0, None), (None, 0.0)])
def test_only_one_of_latitude_and_longitude_is_refused_as_location(client: TestClient, pair: tuple[Any, Any]) -> None:
    before = stored(client)
    assert put(client, body(latitude=pair[0], longitude=pair[1])).status_code == 422
    assert stored(client) == before
    assert put(client, body(latitude=pair[0], longitude=pair[1])).json()["invalid"] == "location"


def test_both_null_clears_the_location(client: TestClient) -> None:
    assert put(client, body()).status_code == 200
    got = put(client, body(latitude=None, longitude=None))
    assert (got.status_code, got.json()["latitude"], got.json()["longitude"]) == (200, None, None)
    assert (stored(client)["latitude"], stored(client)["longitude"]) == (None, None)


@pytest.mark.parametrize("field", ["timezone", "profile", "locale", "unit_system", "clock", "latitude", "longitude"])
def test_a_field_left_out_is_refused_never_kept_or_cleared(client: TestClient, field: str) -> None:
    assert put(client, body()).status_code == 200
    before = stored(client)
    whole = body()
    del whole[field]
    assert_refused_whole(client, whole, before, None)


def test_a_field_the_request_does_not_name_is_refused(client: TestClient) -> None:
    before = stored(client)
    assert_refused_whole(client, {**body(), "id": 99}, before, None)
    assert_refused_whole(client, {**body(), "profile_limit": 1}, before, None)


@pytest.mark.parametrize("field,value", [("timezone", 5), ("profile", 5), ("locale", None), ("latitude", "north"),
                                         ("longitude", [1]), ("profile", None), ("timezone", None)])
def test_a_field_of_the_wrong_type_is_refused(client: TestClient, field: str, value: Any) -> None:
    assert_refused_whole(client, body(**{field: value}), stored(client), None)


def test_a_body_that_is_not_an_object_is_refused(client: TestClient) -> None:
    from household_page_blind_support import ORIGIN, URL
    for raw in ("[]", "null", "42", '"text"', "{"):
        got = client.put(URL, content=raw, headers={**ORIGIN, "content-type": "application/json"})
        assert got.status_code == 422, raw
    assert json.loads(client.get(URL).text)["id"]
