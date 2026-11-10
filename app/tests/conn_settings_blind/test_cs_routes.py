"""`GET|PUT /api/connections/{id}/settings`: a round trip, whole-object replace with compare-and-set on the version, who
may read and write, and the schema's rejections (a rejected write changes nothing)."""

from typing import Any

import pytest
from conn_settings_blind_support import (KEYS, People, as_, connect_ha, empty, read, settings_url, values_of, write,
                                         ORIGIN)
from fastapi.testclient import TestClient

GOOD: dict[str, Any] = {"reads": ["script.find_person"], "service_reads": ["weather.get_forecasts"],
                        "household_reads": {"todo.get_items": ["todo.inbox", "todo.family"]},
                        "consequential_entities": ["switch.lamp"]}


def test_a_new_connection_starts_with_every_setting_empty(client: TestClient) -> None:
    got = read(client, connect_ha(client))
    assert got.status_code == 200
    assert all(empty(got.json()["values"], k) for k in KEYS)
    assert isinstance(got.json()["version"], int) and isinstance(got.json()["schema"], list) and got.json()["schema"]


def test_what_was_put_is_read_back_and_the_version_moves(client: TestClient) -> None:
    cid = connect_ha(client)
    before = int(read(client, cid).json()["version"])
    put = write(client, cid, GOOD)
    assert put.status_code == 200, put.text
    assert put.json()["values"] == GOOD
    assert values_of(client, cid) == GOOD
    assert int(put.json()["version"]) > before


def test_a_stale_version_is_409_and_changes_nothing(client: TestClient) -> None:
    cid = connect_ha(client)
    first = int(read(client, cid).json()["version"])
    assert write(client, cid, GOOD, first).status_code == 200
    stale = write(client, cid, {"reads": ["script.where"]}, first)
    assert stale.status_code == 409
    assert values_of(client, cid) == GOOD


def test_a_put_replaces_the_whole_object(client: TestClient) -> None:
    cid = connect_ha(client)
    write(client, cid, GOOD)
    assert write(client, cid, {"reads": ["script.where"]}).status_code == 200
    got = values_of(client, cid)
    assert got["reads"] == ["script.where"]
    assert all(empty(got, k) for k in ("service_reads", "household_reads", "consequential_entities"))


def test_any_member_of_the_household_may_edit(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    as_(client, people, "sam")
    assert write(client, cid, GOOD).status_code == 200
    as_(client, people, "alana")
    assert values_of(client, cid) == GOOD


def test_no_session_reads_or_writes_nothing(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    as_(client, people, None)
    assert client.get(settings_url(cid)).status_code == 401
    assert client.put(settings_url(cid), json={"version": 1, "values": GOOD}, headers=ORIGIN).status_code == 401
    as_(client, people, "alana")
    assert all(empty(values_of(client, cid), k) for k in KEYS)


def test_another_household_cannot_see_or_change_it(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    write(client, cid, GOOD)
    as_(client, people, "kim")
    assert client.get(settings_url(cid)).status_code == 404
    got = client.put(settings_url(cid), json={"version": 1, "values": {"reads": ["script.where"]}}, headers=ORIGIN)
    assert got.status_code == 404
    as_(client, people, "alana")
    assert values_of(client, cid) == GOOD


def test_a_write_from_another_site_is_refused(client: TestClient) -> None:
    cid = connect_ha(client)
    got = client.put(settings_url(cid), json={"version": 1, "values": GOOD}, headers={"origin": "https://evil.test"})
    assert got.status_code == 403
    assert all(empty(values_of(client, cid), k) for k in KEYS)


def test_a_connection_that_does_not_exist_is_404(client: TestClient) -> None:
    assert client.get(settings_url(987654)).status_code == 404


BAD: list[tuple[str, dict[str, Any]]] = [
    ("unknown key", {"nonsense": ["a.b"]}),
    ("reads a string", {"reads": "script.where"}),
    ("reads holds a number", {"reads": [3]}),
    ("service_reads an object", {"service_reads": {"a": ["b.c"]}}),
    ("household_reads a list", {"household_reads": ["todo.inbox"]}),
    ("household_reads maps to a string", {"household_reads": {"todo.get_items": "todo.inbox"}}),
    ("household_reads maps to numbers", {"household_reads": {"todo.get_items": [1, 2]}}),
    ("consequential_entities an object", {"consequential_entities": {"switch.lamp": True}}),
    ("entity not shaped domain.object", {"consequential_entities": ["Not An Id"]}),
    ("entity with no domain", {"household_reads": {"todo.get_items": ["inbox"]}}),
    ("empty string id", {"consequential_entities": [""]}),
    ("null list", {"reads": None}),
]


@pytest.mark.parametrize(("why", "values"), BAD, ids=[b[0] for b in BAD])
def test_a_value_the_schema_rejects_is_422_and_changes_nothing(client: TestClient, why: str, values: dict[str, Any]) -> None:
    cid = connect_ha(client)
    write(client, cid, GOOD)
    got = write(client, cid, values)
    assert got.status_code == 422, why
    assert values_of(client, cid) == GOOD


def test_a_body_with_no_version_is_422(client: TestClient) -> None:
    cid = connect_ha(client)
    assert client.put(settings_url(cid), json={"values": GOOD}, headers=ORIGIN).status_code == 422


def test_an_entity_the_house_does_not_list_is_kept(client: TestClient) -> None:
    cid = connect_ha(client)
    got = write(client, cid, {"consequential_entities": ["switch.gone_offline"]})
    assert got.status_code == 200 and values_of(client, cid)["consequential_entities"] == ["switch.gone_offline"]
