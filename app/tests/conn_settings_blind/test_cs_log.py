"""The change log: one row per changed key with who and when, no values in what the route serves or the log line says,
and retention enforced by the writer."""

import logging
from collections.abc import Mapping
from typing import Any

import psycopg
import pytest
from conn_settings_blind_support import People, as_, connect_ha, write
from contract.conversations_support import scalar
from fastapi.testclient import TestClient

CHANGE = {"household_reads": {"todo.get_items": ["todo.inbox"]}, "consequential_entities": ["switch.lamp"]}


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[Mapping[str, Any]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def history(client: TestClient, cid: int) -> list[dict[str, Any]]:
    got = client.get(f"/api/connections/{cid}/settings/history")
    assert got.status_code == 200, got.text
    return list(got.json()["items"])


def test_a_change_logs_each_changed_key_with_the_person(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    as_(client, people, "sam")
    assert write(client, cid, CHANGE).status_code == 200
    items = history(client, cid)
    assert {i["key"] for i in items} == {"household_reads", "consequential_entities"}
    assert {i["changed_by"] for i in items} == {people.sam} or {i["changed_by"]["id"] for i in items} == {people.sam}
    assert all(i["changed_at"] for i in items)


def test_an_unchanged_key_is_not_logged_again(client: TestClient) -> None:
    cid = connect_ha(client)
    write(client, cid, CHANGE)
    write(client, cid, {**CHANGE, "reads": ["script.where"]})
    keys = [i["key"] for i in history(client, cid)]
    assert keys.count("reads") == 1 and keys.count("household_reads") == 1


def test_the_history_carries_no_value(client: TestClient) -> None:
    cid = connect_ha(client)
    write(client, cid, CHANGE)
    shown = client.get(f"/api/connections/{cid}/settings/history").text
    assert "todo.inbox" not in shown and "switch.lamp" not in shown


def test_the_log_line_carries_ids_and_key_names_and_no_value(client: TestClient, people: People,
                                                             caplog: pytest.LogCaptureFixture) -> None:
    cid = connect_ha(client)
    caplog.set_level(logging.INFO)
    write(client, cid, CHANGE)
    [line] = events(caplog, "connections.settings.changed")
    assert str(line["household"]) == str(people.home) and str(line["person"]) == str(people.alana)
    assert str(line["connection"]) == str(cid) and line["kind"] == "home_assistant"
    assert "household_reads" in str(line["changed"]) and "consequential_entities" in str(line["changed"])
    assert "todo.inbox" not in repr(caplog.text) and "switch.lamp" not in repr(caplog.text)


def test_a_stale_write_logs_no_change(client: TestClient, db_url: str) -> None:
    cid = connect_ha(client)
    write(client, cid, CHANGE)
    before = int(scalar(db_url, "SELECT count(*) FROM connection_settings_log"))
    assert write(client, cid, {"reads": ["script.where"]}, version=0).status_code == 409
    assert int(scalar(db_url, "SELECT count(*) FROM connection_settings_log")) == before


def age(db_url: str, key: str, days: int) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE connection_settings_log SET changed_at = now() - make_interval(days => %s) WHERE key = %s",
                     (days, key))


def keys_in(db_url: str) -> set[str]:
    with psycopg.connect(db_url) as conn:
        return {str(r[0]) for r in conn.execute("SELECT key FROM connection_settings_log").fetchall()}


def test_retention_prunes_rows_past_the_limit_and_keeps_the_rest(client: TestClient, db_url: str) -> None:
    cid = connect_ha(client)
    write(client, cid, {"reads": ["script.where"], "consequential_entities": ["switch.lamp"]})
    age(db_url, "reads", 500)
    age(db_url, "consequential_entities", 30)
    assert write(client, cid, {"reads": ["script.where"], "consequential_entities": ["switch.lamp"],
                               "service_reads": ["weather.get_forecasts"]}).status_code == 200
    assert keys_in(db_url) == {"consequential_entities", "service_reads"}


def test_retention_prunes_nothing_when_every_row_is_in_limit(client: TestClient, db_url: str) -> None:
    cid = connect_ha(client)
    write(client, cid, {"reads": ["script.where"]})
    age(db_url, "reads", 30)
    write(client, cid, {"reads": ["script.where"], "service_reads": ["weather.get_forecasts"]})
    assert keys_in(db_url) == {"reads", "service_reads"}


def test_the_history_of_another_households_connection_is_404(client: TestClient, people: People) -> None:
    cid = connect_ha(client)
    write(client, cid, CHANGE)
    as_(client, people, "kim")
    assert client.get(f"/api/connections/{cid}/settings/history").status_code == 404
