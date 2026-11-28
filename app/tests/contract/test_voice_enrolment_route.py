"""`POST /api/memory/voice/enrolments` (`ashley.api.voice_enrol`): the signed-in person arms a satellite of their own
household to enrol their voice, and nobody else's. A and B share a household; C has another."""

from collections.abc import Generator
from typing import Any

import pytest
from conversations_support import scalar
from memory_contract_support import WRITE, Cast, household_cast
from voice_support import satellite_row

URL = "/api/memory/voice/enrolments"


@pytest.fixture
def world(db_url: str) -> Generator[Cast]:
    with household_cast(db_url) as c:
        yield c


def post(w: Cast, name: str | None, body: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    return w.as_(name).client.post(URL, json=body, headers=WRITE if headers is None else headers)


def armed(w: Cast) -> list[Any]:
    return list(scalar(w.url, "SELECT coalesce(array_agg(array[device_id, person_id, remaining]), '{}') "
                              "FROM voice_enrolments"))


def test_a_person_arms_a_satellite_for_themselves_with_the_configured_defaults(world: Cast) -> None:
    device = satellite_row(world.url, world.hh["home"]).device.id
    r = post(world, "A", {"device_id": device})
    assert r.status_code == 201, r.text
    assert r.json()["device_id"] == device and r.json()["wakes"] == 6
    assert armed(world) == [[device, world.who["A"], 6]]
    minutes = scalar(world.url, "SELECT round(extract(epoch FROM until - now()) / 60) FROM voice_enrolments")
    assert minutes == 30


def test_wakes_given_are_used_and_a_second_arming_replaces_the_first(world: Cast) -> None:
    device = satellite_row(world.url, world.hh["home"]).device.id
    assert post(world, "A", {"device_id": device, "wakes": 2}).json()["wakes"] == 2
    assert post(world, "B", {"device_id": device, "wakes": 3}).status_code == 201
    assert armed(world) == [[device, world.who["B"], 3]]


def test_a_body_naming_another_person_cannot_arm_them(world: Cast) -> None:
    device = satellite_row(world.url, world.hh["home"]).device.id
    r = post(world, "A", {"device_id": device, "person_id": world.who["B"]})
    assert r.status_code == 201, r.text
    assert armed(world) == [[device, world.who["A"], 6]]


def test_an_unknown_or_other_household_device_is_not_found(world: Cast) -> None:
    far = satellite_row(world.url, world.hh["other"], name="far echo").device.id
    assert post(world, "A", {"device_id": far}).status_code == 404
    assert post(world, "A", {"device_id": far + 1000}).status_code == 404
    assert armed(world) == []


def test_a_device_that_is_not_a_satellite_is_refused(world: Cast) -> None:
    plain = int(scalar(world.url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                                  "VALUES (%s, 'wall tablet', 'hall', 'present', 'text', 'chat', sha256('t'::bytea)) "
                                  "RETURNING id", (world.hh["home"],)))
    r = post(world, "A", {"device_id": plain})
    assert r.status_code == 409 and r.json()["code"] == "refused"
    assert armed(world) == []


def test_bad_wakes_need_a_session_and_the_same_site(world: Cast) -> None:
    device = satellite_row(world.url, world.hh["home"]).device.id
    assert post(world, "A", {"device_id": device, "wakes": 0}).status_code == 422
    assert post(world, None, {"device_id": device}).status_code == 401
    assert post(world, "A", {"device_id": device}, {"Origin": "https://elsewhere.test"}).status_code == 403
    assert armed(world) == []
