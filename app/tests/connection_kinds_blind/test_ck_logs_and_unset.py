"""The routes without the app's `CONNECTIONS_KEY` (nothing can be added, the room says so) and their log lines: one
per list, connect, refusal and removal, with the kind and the outcome, never a secret or an address."""

from collections.abc import Generator

import pytest
from ashley.api.connection_models import ConnectionsResponse
from ashley.api.models import ErrorResponse
from ashley.wiring import CONNECTION_KINDS
from connection_kinds_blind_support import (HOSTS, KIND_NAMES, ORIGIN, SECRETS, Fakes, People, all_logs, app_client,
                                            as_, body_for, log_text)
from fastapi.testclient import TestClient
from connection_routes_support import delete_kind, put_kind


def host_of(kind: str) -> str:
    return next(h for h, k in HOSTS.items() if k == kind)


@pytest.fixture
def keyless(db_url: str, people: People, fakes: Fakes) -> Generator[TestClient]:
    for c in app_client(db_url, fakes, key=""):
        as_(c, people, "alana")
        yield c


def test_without_the_key_nothing_is_connected_and_the_kinds_are_still_offered(keyless: TestClient) -> None:
    got = keyless.get("/api/connections")
    assert got.status_code == 200
    body = ConnectionsResponse.model_validate(got.json())
    assert body.can_connect is False and body.connections == []
    assert [o.name for o in body.offered] == [k.name for k in CONNECTION_KINDS if k.name != "herdr"]


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_without_the_key_a_connect_is_503_unavailable_and_asks_nothing(keyless: TestClient, fakes: Fakes,
                                                                        kind: str) -> None:
    got = put_kind(keyless, kind, json=body_for(kind), headers=ORIGIN)
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"
    assert fakes.seen == []
    assert SECRETS[kind] not in got.text


@pytest.mark.parametrize("kind", KIND_NAMES)
def test_a_connection_made_listed_refused_and_removed_is_logged_without_its_secret_or_address(
        client: TestClient, fakes: Fakes, caplog: pytest.LogCaptureFixture, kind: str) -> None:
    all_logs(caplog)
    put_kind(client, kind, json=body_for(kind), headers=ORIGIN)
    client.get("/api/connections")
    fakes.mode[kind] = "refuse"
    put_kind(client, kind, json=body_for(kind), headers=ORIGIN)
    fakes.mode[kind] = "ok"
    delete_kind(client, kind, headers=ORIGIN)
    text = log_text(caplog, "ashley.api")
    assert kind in text
    for hidden in (SECRETS[kind], host_of(kind)):
        assert hidden not in log_text(caplog)


def test_each_list_connect_refusal_and_removal_is_one_logged_event_with_the_kind(
        client: TestClient, fakes: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)
    client.get("/api/connections")
    listed = {r.getMessage() for r in caplog.records if r.name.startswith("ashley.api")}
    put_kind(client, "sure", json=body_for("sure"), headers=ORIGIN)
    fakes.mode["sure"] = "refuse"
    put_kind(client, "sure", json=body_for("sure"), headers=ORIGIN)
    delete_kind(client, "sure", headers=ORIGIN)
    events = [r for r in caplog.records if r.name.startswith("ashley.api") and r.getMessage().startswith("connections.")
              and r.getMessage() != "connections.listed"]
    assert len(events) == 3 and len({r.getMessage() for r in events}) == 3 and listed
    assert [r for r in events if getattr(r, "fields", {}).get("kind") != "sure"] == []
