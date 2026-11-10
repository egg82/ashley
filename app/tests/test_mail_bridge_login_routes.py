"""Logging a Proton account in from the room (`ashley.api.mail_bridge_login`) through the real app and record, with Bridge's
login scripted at `ProtonLogin`: each step is relayed once; a connected account is stored as a connection whose secret is
the password Bridge issued; a second login to the same account replaces it and clears `needs`; a label that is another
account's, or a person's limit, is refused (and Bridge told to forget the user); nothing typed or issued reaches a log
line or a response; the account list shows only what the person can see, with its syncing state."""

import base64
import logging
import os
from typing import Literal, get_args
from collections.abc import Generator
from dataclasses import dataclass

import psycopg
import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.sealing import VERSION, Sealer, bound_to, key_from
from ashley.db.database import Database
from ashley.mail.proton_bridge import ProtonBridge
from ashley.mail.proton_bridge_postgres import PostgresProtonBridge
from ashley.mail.proton_login import Ask, Done, ProtonLogin, Refused, Verify
from ashley.main import create_app
from ashley.people import admin
from ashley.api.person import SESSION_COOKIE
from ashley.settings import Settings
from ashley.wiring import CONNECTION_KINDS
from ashley.mail.proton_kind import PROTON
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from mail_bridge_support import KEY, ScriptedLogin, logged, signed_in_token

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
APP_KEY = base64.b64encode(os.urandom(32)).decode()
Reason = Literal["credentials", "code", "mailbox_password", "paid_plan", "connection", "aborted", "verification",
                 "security_key", "other"]
PASSWORD, BRIDGE_PASSWORD, CODE = "typed-proton-password", "issued-bridge-password", "123456"


@dataclass(frozen=True)
class Homes:
    alana: int
    sam: int
    alana_token: str
    sam_token: str


@pytest.fixture
def homes(db_url: str) -> Homes:
    with psycopg.connect(db_url) as conn:
        home = admin.add_household(conn, "home", "UTC")
        alana, sam = admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam")
    return Homes(alana, sam, signed_in_token(db_url, home, alana, "sub-alana"), signed_in_token(db_url, home, sam, "sub-sam"))


def done(user: str = "user-1", password: str = BRIDGE_PASSWORD, synced: bool = False) -> Done:
    return Done(user, (f"{user}@proton.test", f"{user}+two@proton.test"), password, 1, synced)


@pytest.fixture
def script() -> ScriptedLogin:
    return ScriptedLogin()


@pytest.fixture
def client(db_url: str, homes: Homes, script: ScriptedLogin) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(ConnectionKinds, ConnectionKinds((*CONNECTION_KINDS, PROTON)))
        services.register(ProtonBridge, PostgresProtonBridge(services.get(Database), Sealer({VERSION: KEY})))
        services.register(ProtonLogin, script)
        c.cookies.set(SESSION_COOKIE, homes.alana_token, domain="ashley.test")
        yield c
    services.unregister(Connections)


def login(client: TestClient, label: str = "work", password: str = PASSWORD) -> dict[str, object]:
    got = client.post("/api/mail-bridge/login", json={"label": label, "username": "alana@proton.test",
                                                      "password": password}, headers=ORIGIN)
    return {"status": got.status_code, **got.json()}


def test_a_login_without_a_second_step_stores_a_connection_with_the_password_bridge_issued(
        client: TestClient, script: ScriptedLogin, db_url: str, homes: Homes, caplog: pytest.LogCaptureFixture) -> None:
    script.steps = [done()]
    with caplog.at_level(logging.INFO):
        got = login(client)
    assert got["status"] == 200 and got["step"] == "connected" and got["addresses"] == [
        "user-1@proton.test", "user-1+two@proton.test"]
    assert script.calls == ["begin"] and script.seen == ["alana@proton.test", PASSWORD]
    connection = client.get("/api/connections").json()["connections"][0]
    assert (connection["kind"], connection["label"], connection["personal"], connection["id"]) == (
        "proton", "work", True, got["connection_id"])
    assert scalar(db_url, "SELECT count(*) FROM proton_bridge_accounts") == 1
    assert scalar(db_url, "SELECT synced_epoch FROM proton_bridge_accounts") == 0
    sealed = bytes(scalar(db_url, "SELECT secret FROM connections"))
    assert Sealer({VERSION: key_from(APP_KEY)}).open(sealed, bound_to(1, "proton", homes.alana)) == BRIDGE_PASSWORD
    text = " ".join(f"{m} {f}" for m, f in logged(caplog)) + str(got) + client.get("/api/connections").text
    assert PASSWORD not in text and BRIDGE_PASSWORD not in text and "alana@proton.test" not in text
    assert ("proton_bridge.login", {"household": scalar(db_url, "SELECT household_id FROM people WHERE id = %s",
                                                        (homes.alana,)), "person": homes.alana, "outcome": "connected",
                                   "connection": got["connection_id"]}) in logged(caplog)


def test_the_two_steps_are_relayed_in_turn_and_the_account_keeps_its_sync(
        client: TestClient, script: ScriptedLogin, db_url: str) -> None:
    script.steps = [Ask("two_factor"), Ask("mailbox_password"), done(synced=True)]
    first = login(client)
    assert (first["status"], first["step"]) == (200, "two_factor")
    second = client.post("/api/mail-bridge/login/two-factor", json={"label": "work", "code": CODE}, headers=ORIGIN)
    assert second.json()["step"] == "mailbox_password"
    third = client.post("/api/mail-bridge/login/mailbox-password", json={"label": "work", "password": "pw2"},
                        headers=ORIGIN)
    assert third.json()["step"] == "connected"
    assert script.calls == ["begin", "second_factor", "mailbox_password"] and script.seen[-2:] == [CODE, "pw2"]
    assert scalar(db_url, "SELECT synced_epoch FROM proton_bridge_accounts") == 1


@pytest.mark.parametrize("reason", get_args(Reason))
def test_a_step_bridge_refuses_ends_the_login_and_stores_nothing(
        client: TestClient, script: ScriptedLogin, db_url: str, reason: Reason) -> None:
    script.steps = [Refused(reason)]
    got = login(client)
    assert got["status"] == 400 and got["reason"] == reason
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_human_check_is_relayed_with_its_page_and_the_verified_retry_connects(
        client: TestClient, script: ScriptedLogin, caplog: pytest.LogCaptureFixture) -> None:
    url = "https://verify.proton.me/?token=SECRET"
    script.steps = [Verify(url), done()]
    with caplog.at_level(logging.INFO):
        first = login(client)
        again = client.post("/api/mail-bridge/login/verified", json={"label": "work", "password": PASSWORD},
                            headers=ORIGIN)
    assert first == {"status": 200, "step": "human_verification", "connection_id": None, "addresses": [],
                     "verification_url": url}
    assert again.json()["step"] == "connected" and script.calls == ["begin", "verified"]
    assert script.seen[-1] == PASSWORD
    assert "SECRET" not in " ".join(f"{m} {f}" for m, f in logged(caplog))


def test_logging_in_again_to_a_signed_out_account_replaces_its_secret_and_clears_needs(
        client: TestClient, script: ScriptedLogin, db_url: str) -> None:
    script.steps = [done(), done(password="a-new-password", synced=True)]
    first = login(client)
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE proton_bridge SET epoch = 1; UPDATE proton_bridge_accounts SET state = 'signed_out'; "
                     "UPDATE connections SET needs = 'login'")
    second = login(client, label="renamed")
    assert second["connection_id"] == first["connection_id"]
    assert scalar(db_url, "SELECT count(*) FROM connections") == 1
    assert scalar(db_url, "SELECT needs FROM connections") is None
    assert scalar(db_url, "SELECT state FROM proton_bridge_accounts") == "connected"
    assert scalar(db_url, "SELECT secret_version FROM connections") == 2


def test_a_label_that_is_another_accounts_is_refused_and_bridge_forgets_the_user(
        client: TestClient, script: ScriptedLogin, db_url: str) -> None:
    script.steps = [done("user-1"), done("user-2")]
    login(client)
    got = login(client, label="work")
    assert got["status"] == 400 and got["reason"] == "label_taken"
    assert script.calls == ["begin", "begin", "forget user-2"]
    assert scalar(db_url, "SELECT count(*) FROM proton_bridge_accounts") == 1


def test_a_person_at_the_kinds_limit_is_refused_before_bridge_is_asked(
        client: TestClient, script: ScriptedLogin) -> None:
    script.steps = [done(f"user-{n}") for n in range(PROTON.most)]
    for n in range(PROTON.most):
        assert login(client, label=f"l{n}")["status"] == 200
    got = login(client, label="one-more")
    assert got["status"] == 400 and got["reason"] == "too_many"
    assert script.calls == ["begin"] * PROTON.most


def test_no_bridge_running_is_503_and_a_kind_not_registered_is_404(client: TestClient) -> None:
    services.unregister(ProtonLogin)
    assert login(client)["status"] == 503
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    assert login(client)["status"] == 404


def test_a_login_from_another_site_is_refused(client: TestClient) -> None:
    got = client.post("/api/mail-bridge/login", json={"label": "w", "username": "a", "password": "b"},
                      headers={"origin": "https://elsewhere.test"})
    assert got.status_code == 403


def test_the_account_list_shows_what_the_person_can_see_and_whether_it_is_syncing(
        client: TestClient, script: ScriptedLogin, db_url: str, homes: Homes) -> None:
    script.steps = [done("user-1")]
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE proton_bridge SET epoch = 1")
    login(client)
    mine = client.get("/api/mail-bridge/accounts").json()["proton_accounts"]
    assert [(a["state"], a["syncing"], a["sync_progress"]) for a in mine] == [("connected", True, None)]
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE proton_bridge_accounts SET synced_epoch = 1")
    assert client.get("/api/mail-bridge/accounts").json()["proton_accounts"][0]["syncing"] is False
    client.cookies.set(SESSION_COOKIE, homes.sam_token, domain="ashley.test")
    assert client.get("/api/mail-bridge/accounts").json() == {"proton_accounts": []}
