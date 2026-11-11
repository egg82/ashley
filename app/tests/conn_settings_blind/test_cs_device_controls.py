"""A device's touch controls on a real database: the Devices room's edit route (every light must be in the house's
catalogue, another household's device is refused), the kiosk reading its own device's controls per request, a fresh
household having none, and the migration seeding none, household 1's hallway tablet included."""

import hashlib
from collections.abc import Generator

import psycopg
import pytest
from alembic import command
from ashley.db.migrate import alembic_config
from conn_settings_blind_support import ORIGIN, People, app_client, as_, connect_ha, people_in
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from httpx2 import Response
from house_double_support import MemoryHouse, state

KIOSK = "__Host-ashley_kiosk"
HALL: dict[str, str | None] = {"label": "Hall light", "action": "light.turn_on", "entity_id": "light.zq_hall"}
PORCH: dict[str, str | None] = {"label": "Porch off", "action": "light.turn_off", "entity_id": "light.zq_porch"}


def lit_house() -> MemoryHouse:
    return MemoryHouse(things=[state("light.zq_hall", "Hall", "off"), state("light.zq_porch", "Porch", "on"),
                               state("lock.zq_front", "Front", "locked"), state("scene.zq_night", "Night", "unknown")])


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    with app_client(db_url, people, {people.home: lit_house(), people.other: lit_house()}) as c:
        as_(c, people, "alana")
        connect_ha(c)
        yield c


def device(url: str, household: int, token: str, place: str = "hallway") -> int:
    return int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                      "VALUES (%s, 'tablet', %s, 'present', 'text', 'chat', %s) RETURNING id",
                      (household, place, hashlib.sha256(token.encode()).digest())))


def put(client: TestClient, device_id: int, *controls: dict[str, str | None], base: int | None = None) -> Response:
    """The list put over what the room read last, unless `base` names another version."""
    version = client.get(f"/api/devices/{device_id}/controls").json()["piece_version"] if base is None else base
    return client.put(f"/api/devices/{device_id}/controls",
                      json={"wanted": list(controls), "base_version": version}, headers=ORIGIN)


def kiosk_controls(client: TestClient, token: str) -> list[dict[str, str]]:
    got = client.get("/api/kiosk/controls", headers={"cookie": f"{KIOSK}={token}"})
    assert got.status_code == 200, got.text
    return list(got.json()["controls"])


def test_a_person_sets_the_controls_and_the_kiosk_reads_them_in_order(client: TestClient, db_url: str,
                                                                      people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    saved = put(client, mine, PORCH, {**HALL, "name": None})
    assert saved.status_code == 200, saved.text
    assert [(c["name"], c["entity_id"]) for c in saved.json()["device_controls"]] == [
        ("porch-off", "light.zq_porch"), ("hall-light", "light.zq_hall")]
    assert client.get(f"/api/devices/{mine}/controls").json() == saved.json()
    assert kiosk_controls(client, "tok-a") == [{"name": "porch-off", "label": "Porch off"},
                                               {"name": "hall-light", "label": "Hall light"}]


def test_a_light_the_catalogue_does_not_have_is_refused_and_nothing_is_stored(client: TestClient, db_url: str,
                                                                               people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert put(client, mine, HALL).status_code == 200
    for bad in ({**PORCH, "entity_id": "light.zq_nowhere"}, {**PORCH, "entity_id": "lock.zq_front"}):
        got = put(client, mine, PORCH, bad)
        assert got.status_code == 422 and got.json()["reason"] == "unknown_entity"
    assert [c["name"] for c in kiosk_controls(client, "tok-a")] == ["hall-light"]


def test_a_scene_takes_only_its_own_action_and_a_light_never_does(client: TestClient, db_url: str,
                                                                    people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    night: dict[str, str | None] = {"label": "Night", "action": "scene.turn_on", "entity_id": "scene.zq_night"}
    assert put(client, mine, night).status_code == 200
    for bad in ({**night, "action": "light.turn_on"}, {**HALL, "action": "scene.turn_on"}):
        got = put(client, mine, bad)
        assert got.status_code == 422 and got.json()["reason"] == "unknown_entity"
    assert [c["name"] for c in kiosk_controls(client, "tok-a")] == ["night"]


def test_a_household_with_no_house_cannot_store_a_light(db_url: str, people: People) -> None:
    with app_client(db_url, people, {}) as c:
        as_(c, people, "alana")
        mine = device(db_url, people.home, "tok-a")
        assert put(c, mine, HALL).status_code == 422
        assert put(c, mine).status_code == 200


def test_another_households_device_is_not_found_and_stays_as_it_was(client: TestClient, db_url: str,
                                                                    people: People) -> None:
    theirs = device(db_url, people.other, "tok-b")
    assert put(client, theirs, HALL, base=0).status_code == 404
    assert client.get(f"/api/devices/{theirs}/controls").status_code == 404
    assert kiosk_controls(client, "tok-b") == []


def test_a_fresh_households_device_has_none(client: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert client.get(f"/api/devices/{mine}/controls").json() == {"device_controls": [], "piece_version": 0}
    assert kiosk_controls(client, "tok-a") == []


def test_one_devices_controls_never_show_on_another(client: TestClient, db_url: str, people: People) -> None:
    one, two = device(db_url, people.home, "tok-1"), device(db_url, people.home, "tok-2")
    put(client, one, HALL)
    assert kiosk_controls(client, "tok-2") == [] and len(kiosk_controls(client, "tok-1")) == 1
    assert put(client, two).status_code == 200
    assert len(kiosk_controls(client, "tok-1")) == 1


def test_an_empty_list_clears_them_and_no_session_is_refused(client: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    put(client, mine, HALL)
    assert put(client, mine).status_code == 200 and kiosk_controls(client, "tok-a") == []
    as_(client, people, None)
    assert client.get(f"/api/devices/{mine}/controls").status_code == 401


def test_the_migration_seeds_no_controls_not_even_on_household_ones_hallway_tablet(empty_database: str) -> None:
    url = empty_database
    command.upgrade(alembic_config(url), "0087")
    with psycopg.connect(url, autocommit=True) as conn:
        for name in ("Moore", "Other"):
            conn.execute("INSERT INTO households (name, timezone) VALUES (%s, 'UTC')", (name,))
    moore, other = (int(scalar(url, "SELECT id FROM households WHERE name = %s", (n,))) for n in ("Moore", "Other"))
    assert moore == 1
    tablet, kitchen, theirs = (device(url, moore, "t1"), device(url, moore, "t2", "kitchen"), device(url, other, "t3"))
    command.upgrade(alembic_config(url), "head")
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT device_id, name, position, action, entity_id FROM device_controls "
                            "ORDER BY device_id, position").fetchall()
    assert {tablet, kitchen, theirs} and rows == []


TOGGLE_HALL: dict[str, str | None] = {"label": "Hall", "action": "light.toggle", "entity_id": "light.zq_hall"}
TOGGLE_PORCH: dict[str, str | None] = {"label": "Porch", "action": "light.toggle", "entity_id": "light.zq_porch"}


@pytest.fixture
def house() -> MemoryHouse:
    return lit_house()


@pytest.fixture
def toggling(db_url: str, people: People, house: MemoryHouse) -> Generator[TestClient]:
    with app_client(db_url, people, {people.home: house, people.other: lit_house()}) as c:
        as_(c, people, "alana")
        connect_ha(c)
        yield c


@pytest.mark.xfail(strict=True, reason="light.toggle is not an action yet")
def test_a_light_toggle_is_stored_and_a_scene_cannot_take_it(toggling: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    saved = put(toggling, mine, TOGGLE_HALL)
    assert saved.status_code == 200, saved.text
    assert [c["action"] for c in saved.json()["device_controls"]] == ["light.toggle"]
    night: dict[str, str | None] = {"label": "Night", "action": "light.toggle", "entity_id": "scene.zq_night"}
    assert put(toggling, mine, night).status_code == 422


@pytest.mark.xfail(strict=True, reason="a toggle's button is not told whether its light is on yet")
def test_the_kiosk_reads_whether_a_toggles_light_is_on_and_says_nothing_otherwise(toggling: TestClient, db_url: str,
                                                                                  people: People,
                                                                                  house: MemoryHouse) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert put(toggling, mine, TOGGLE_HALL, TOGGLE_PORCH, PORCH).status_code == 200
    assert [(c["name"], c["on"]) for c in kiosk_controls(toggling, "tok-a")] == [
        ("hall", False), ("porch", True), ("porch-off", None)]
    house.down = True
    assert [c["on"] for c in kiosk_controls(toggling, "tok-a")] == [None, None, None]


@pytest.mark.xfail(strict=True, reason="light.toggle is not an action yet")
def test_pressing_a_toggle_runs_light_toggle_on_its_light_through_the_house(toggling: TestClient, db_url: str,
                                                                            people: People, house: MemoryHouse) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert put(toggling, mine, TOGGLE_PORCH).status_code == 200
    pressed = toggling.post("/api/kiosk/controls/porch", headers={**ORIGIN, "cookie": f"{KIOSK}=tok-a"})
    assert pressed.status_code == 200 and pressed.json() == {"done": True}
    assert [d[2:4] for d in house.done] == [("light.toggle", ("light.zq_porch",))]
