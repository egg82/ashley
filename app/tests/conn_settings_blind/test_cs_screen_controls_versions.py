"""The Devices room's edit of a device's buttons is an Edit of the screen's controls piece naming the version it read:
a second edit from the same read is refused 409 `stale`, nothing is stored, and the buttons are moved into the piece on
the first edit."""

from typing import Any

import psycopg
from conn_settings_blind_support import ORIGIN, People
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from httpx2 import Response
from test_cs_device_controls import HALL, PORCH, client as client, device, people as people, put


def read(client: TestClient, device_id: int) -> dict[str, Any]:
    got = client.get(f"/api/devices/{device_id}/controls")
    assert got.status_code == 200, got.text
    return dict(got.json())


def put_at(client: TestClient, device_id: int, base: int, *controls: dict[str, str | None]) -> Response:
    return client.put(f"/api/devices/{device_id}/controls", json={"wanted": list(controls), "base_version": base},
                      headers=ORIGIN)


def test_the_version_is_zero_until_the_screen_is_laid_out_and_rises_by_one_per_edit(client: TestClient, db_url: str,
                                                                                    people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert read(client, mine)["piece_version"] == 0
    first = put_at(client, mine, 0, HALL)
    assert first.status_code == 200, first.text
    after_first = int(first.json()["piece_version"])
    assert read(client, mine)["piece_version"] == after_first
    second = put_at(client, mine, after_first, HALL, PORCH)
    assert second.status_code == 200 and second.json()["piece_version"] == after_first + 1


def test_an_edit_from_a_stale_read_is_409_stale_and_stores_nothing(client: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    seen = int(read(client, mine)["piece_version"])
    assert put_at(client, mine, seen, HALL).status_code == 200
    stale = put_at(client, mine, seen, PORCH)
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    assert [c["name"] for c in read(client, mine)["device_controls"]] == ["hall-light"]
    assert put_at(client, mine, 99, PORCH).status_code == 409


def test_the_first_edit_moves_the_old_rows_into_the_piece_and_empties_the_table(client: TestClient, db_url: str,
                                                                                 people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("INSERT INTO device_controls (device_id, household_id, name, position, label, action, entity_id) "
                     "VALUES (%s, %s, 'porch-off', 0, 'Porch off', 'light.turn_off', 'light.zq_porch')", (mine, people.home))
    assert [c["name"] for c in read(client, mine)["device_controls"]] == ["porch-off"]
    assert put(client, mine, PORCH, HALL).status_code == 200
    assert int(scalar(db_url, "SELECT count(*) FROM device_controls WHERE device_id = %s", (mine,))) == 0
    assert [c["name"] for c in read(client, mine)["device_controls"]] == ["porch-off", "hall-light"]


def test_a_screen_bench_is_not_a_benchs_route_nor_in_the_list(client: TestClient, db_url: str, people: People) -> None:
    mine = device(db_url, people.home, "tok-a")
    assert put_at(client, mine, 0, HALL).status_code == 200
    bench = int(scalar(db_url, "SELECT id FROM benches WHERE device_id = %s", (mine,)))
    for path in (f"/api/benches/{bench}", f"/api/benches/{bench}/talk"):
        assert client.get(path).status_code == 404, path
    listed = client.get("/api/benches")
    assert listed.status_code == 200 and bench not in [b["id"] for b in listed.json()["benches"]]
