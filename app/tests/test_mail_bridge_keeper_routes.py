"""What the keeper calls (`ashley.api.mail_bridge`) through the real app and record: the token of the epoch is the only
credential; a pod of an old epoch is refused with 409 on every call; a write-back lands only at the generation the keeper
read; an unreachable record is 503; the vault and the token never reach a log line."""

import base64
import logging
from collections.abc import Generator

import psycopg
import pytest
from ashley import services
from ashley.connections.sealing import VERSION, Sealer
from ashley.db.database import Database
from ashley.mail.proton_bridge import ProtonBridge
from ashley.mail.proton_bridge_postgres import PostgresProtonBridge, token_sha256
from ashley.main import create_app
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from mail_bridge_support import KEY, logged

PATH = "/api/mail-bridge/keeper"
TOKEN = "token-of-epoch-one"
VAULT = base64.b64encode(b"vault-bytes-0123456789").decode()
KEYCHAIN = base64.b64encode(b"keychain-bytes").decode()
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(db_url: str) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t"))
    with TestClient(app, base_url="https://ashley.test") as c:
        bridge = PostgresProtonBridge(services.get(Database), Sealer({VERSION: KEY}))
        services.register(ProtonBridge, bridge)
        _epoch(db_url, 1, TOKEN)
        yield c


def _epoch(url: str, epoch: int, token: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE proton_bridge SET epoch = %s, site = 'birch', pod = 'p', token_sha256 = %s, "
                     "started_at = now()", (epoch, token_sha256(token)))


def test_the_token_of_the_epoch_is_the_only_credential(client: TestClient) -> None:
    ok = client.post(f"{PATH}/heartbeat", json={"epoch": 1}, headers=AUTH)
    assert ok.status_code == 204
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": TOKEN}):
        got = client.post(f"{PATH}/heartbeat", json={"epoch": 1}, headers=headers)
        assert got.status_code == 401 and got.json()["code"] == "unauthorized"
    assert client.get(f"{PATH}/vault", params={"epoch": 1}).status_code == 401


def test_an_old_epoch_is_refused_on_every_call(client: TestClient, db_url: str) -> None:
    _epoch(db_url, 2, "next")
    for got in (client.post(f"{PATH}/heartbeat", json={"epoch": 1}, headers=AUTH),
                client.get(f"{PATH}/vault", params={"epoch": 1}, headers=AUTH),
                client.put(f"{PATH}/vault", json={"epoch": 1, "generation": 0, "vault": VAULT, "keychain": KEYCHAIN},
                           headers=AUTH),
                client.post(f"{PATH}/events", json={"epoch": 1, "user_id": "u", "sync": "finished"}, headers=AUTH)):
        assert got.status_code == 409 and got.json()["code"] == "refused"


def test_a_write_back_lands_at_its_generation_and_the_next_must_carry_the_new_one(
        client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    first = client.get(f"{PATH}/vault", params={"epoch": 1}, headers=AUTH).json()
    assert first == {"generation": 0, "vault": None, "keychain": None}
    body = {"epoch": 1, "generation": 0, "vault": VAULT, "keychain": KEYCHAIN}
    with caplog.at_level(logging.INFO, logger="ashley.api"):
        wrote = client.put(f"{PATH}/vault", json=body, headers=AUTH)
        stale = client.put(f"{PATH}/vault", json=body, headers=AUTH)
    assert wrote.json() == {"generation": 1} and stale.status_code == 409
    again = client.get(f"{PATH}/vault", params={"epoch": 1}, headers=AUTH).json()
    assert again == {"generation": 1, "vault": VAULT, "keychain": KEYCHAIN}
    assert ("proton_bridge.written_back", {"epoch": 1, "generation": 1, "bytes": len(VAULT)}) in logged(caplog)
    assert ("proton_bridge.refused", {"epoch": 1, "call": "write_back", "reason": "stale_generation"}) in logged(caplog)
    text = " ".join(f"{m} {f}" for m, f in logged(caplog))
    assert VAULT not in text and TOKEN not in text


def test_a_vault_that_is_not_base64_is_a_422(client: TestClient) -> None:
    got = client.put(f"{PATH}/vault", json={"epoch": 1, "generation": 0, "vault": "!!", "keychain": KEYCHAIN},
                     headers=AUTH)
    assert got.status_code == 422


def test_an_unreachable_record_is_503(client: TestClient) -> None:
    services.unregister(ProtonBridge)
    for got in (client.post(f"{PATH}/heartbeat", json={"epoch": 1}, headers=AUTH),
                client.put(f"{PATH}/vault", json={"epoch": 1, "generation": 0, "vault": VAULT, "keychain": KEYCHAIN},
                           headers=AUTH)):
        assert got.status_code == 503 and got.json()["code"] == "unavailable"


@pytest.mark.parametrize("event", [{"state": "signed_out", "sync": "started"}, {}, {"sync": "progress"},
                                   {"sync": "finished", "progress": 0.5}, {"sync": "progress", "progress": 2}])
def test_an_event_is_a_state_or_a_sync_and_progress_goes_with_progress(client: TestClient, event: dict[str, object]) -> None:
    got = client.post(f"{PATH}/events", json={"epoch": 1, "user_id": "u", **event}, headers=AUTH)
    assert got.status_code == 422


def test_an_event_for_a_user_no_connection_holds_changes_nothing(client: TestClient) -> None:
    got = client.post(f"{PATH}/events", json={"epoch": 1, "user_id": "nobody", "state": "signed_out"}, headers=AUTH)
    assert got.status_code == 200 and got.json() == {"applied": False}
