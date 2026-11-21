"""The signed-in person's own voiceprints on the memory page's API (`ashley.api.memory`, `decisions.md`, "A voice names
the speaker as a hint"): listed and forgotten for the session's person alone. A and B share a household; C has another."""

from collections.abc import Generator
from typing import Any

import pytest
from conversations_support import scalar
from memory_contract_support import WRITE, Cast, household_cast
from voice_support import satellite_row

VOICE = "/api/memory/voice"


@pytest.fixture
def world(db_url: str) -> Generator[Cast]:
    with household_cast(db_url) as c:
        yield c


def enrol(w: Cast, household: str, person: str, device: int, vector: str = "[1,0]") -> None:
    scalar(w.url, "INSERT INTO voiceprints (household_id, person_id, model, vector, device_id) "
                  "VALUES (%s, %s, 'titanet', %s::vector, %s) RETURNING id",
           (w.hh[household], w.who[person], vector, device))


def count(w: Cast, person: str) -> int:
    return int(scalar(w.url, "SELECT count(*) FROM voiceprints WHERE person_id = %s", (w.who[person],)))


def seed(w: Cast) -> None:
    echo = satellite_row(w.url, w.hh["home"], name="kitchen echo").device.id
    other = satellite_row(w.url, w.hh["other"], name="far echo").device.id
    enrol(w, "home", "A", echo)
    enrol(w, "home", "A", echo)
    enrol(w, "home", "B", echo, "[0,1]")
    enrol(w, "other", "C", other)
    scalar(w.url, "INSERT INTO voice_enrolments (device_id, household_id, person_id, remaining, until) "
                  "VALUES (%s, %s, %s, 3, now() + interval '1 hour') RETURNING device_id",
           (echo, w.hh["home"], w.who["A"]))


def listed(w: Cast, name: str) -> list[dict[str, Any]]:
    r = w.get(name, VOICE)
    assert r.status_code == 200, r.text
    return list(r.json()["prints"])


def test_a_person_sees_their_own_prints_by_device_and_time_and_never_the_vector(world: Cast) -> None:
    seed(world)
    mine = listed(world, "A")
    assert len(mine) == 2
    assert all(set(p) == {"device", "enrolled_at"} and p["device"] == "kitchen echo" for p in mine)
    assert len(listed(world, "B")) == 1 and len(listed(world, "C")) == 1


def test_a_person_with_no_prints_sees_an_empty_list(world: Cast) -> None:
    assert listed(world, "A") == []


def test_forgetting_deletes_only_the_signed_in_persons_prints_and_their_armed_enrolment(world: Cast) -> None:
    seed(world)
    r = world.as_("A").client.delete(VOICE, headers=WRITE)
    assert r.status_code == 200 and r.json() == {"deleted": 2}
    assert (count(world, "A"), count(world, "B"), count(world, "C")) == (0, 1, 1)
    assert scalar(world.url, "SELECT count(*) FROM voice_enrolments") == 0
    assert world.as_("A").client.delete(VOICE, headers=WRITE).json() == {"deleted": 0}


def test_the_routes_need_a_session_and_a_forget_needs_the_same_site(world: Cast) -> None:
    seed(world)
    assert world.get(None, VOICE).status_code == 401
    assert world.as_(None).client.delete(VOICE, headers=WRITE).status_code == 401
    assert world.as_("A").client.delete(VOICE, headers={"Origin": "https://elsewhere.test"}).status_code == 403
    assert count(world, "A") == 2
