"""Logging in from the room (design: "Logging in happens once, from the room ... Nothing typed is stored or logged: Bridge
keeps the session in the vault, and the write-back stores it"). The app relays to a fake keeper; the real app and
database store whatever they store."""

import logging
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from ashley import services
from ashley.connections.connections import Connections
from mail_bridge_blind_keeper_support import TOKEN, FakeKeeperHttp
from mail_bridge_blind_kube_support import texts, wire_login
from mail_bridge_blind_support import World, app_client, dump, make_world

USERNAME, PASSWORD, CODE, MAILBOX_PASSWORD = "login-name-xq", "pw-Zk39-typed", "482915", "mbx-Rt77-typed"
BRIDGE_PASSWORD = "bridge-issued-Hn42"
ADDRESSES = ["alana@proton.test", "family@proton.test"]
ROOM = "/api/mail-bridge/login"
LABEL = "Alana Proton"
ORIGIN = {"origin": "https://ashley.test"}
DONE: dict[str, Any] = {"step": "connected", "user_id": "u-proton-1", "addresses": ADDRESSES, "bridge_password": BRIDGE_PASSWORD,
                        "epoch": 1, "synced": False}


def keeper_script(two_passwords: bool = False) -> dict[str, tuple[int, dict[str, Any]]]:
    after_password: dict[str, Any] = {"step": "two_factor"}
    after_code: dict[str, Any] = {"step": "mailbox_password"} if two_passwords else DONE
    return {"/login": (200, after_password), "/login/two-factor": (200, after_code), "/login/mailbox-password": (200, DONE)}


@pytest.fixture
def keeper(tmp_path: Path) -> Generator[FakeKeeperHttp]:
    fake = FakeKeeperHttp(keeper_script(), tmp_path)
    yield fake
    fake.stop()


@pytest.fixture
def room(db_url: str, keeper: FakeKeeperHttp) -> Generator[World]:
    for c in app_client(db_url):
        w = make_world(db_url, c)
        wire_login(w, keeper.url, keeper.cert, TOKEN)
        w.sign_in()
        yield w


def post(world: World, path: str, **body: str) -> int:
    return world.client.post(ROOM + path, json={"label": LABEL, **body}, headers=ORIGIN).status_code


def full_login(world: World) -> None:
    assert post(world, "", username=USERNAME, password=PASSWORD) == 200
    assert post(world, "/two-factor", code=CODE) == 200


def test_each_step_is_relayed_to_the_keeper_in_order_with_what_was_typed(room: World, keeper: FakeKeeperHttp) -> None:
    full_login(room)
    assert keeper.steps == [("/login", {"username": USERNAME, "password": PASSWORD}), ("/login/two-factor", {"code": CODE})]


def test_an_account_with_two_passwords_is_asked_for_the_mailbox_password_after_the_code(db_url: str, tmp_path: Path) -> None:
    fake = FakeKeeperHttp(keeper_script(two_passwords=True), tmp_path)
    try:
        for c in app_client(db_url):
            w = make_world(db_url, c)
            wire_login(w, fake.url, fake.cert, TOKEN)
            w.sign_in()
            assert post(w, "", username=USERNAME, password=PASSWORD) == 200
            assert w.client.post(ROOM + "/two-factor", json={"label": LABEL, "code": CODE},
                                 headers=ORIGIN).json()["step"] == "mailbox_password"
            assert post(w, "/mailbox-password", password=MAILBOX_PASSWORD) == 200
            assert [p for p, _ in fake.steps] == ["/login", "/login/two-factor", "/login/mailbox-password"]
    finally:
        fake.stop()


def test_a_finished_login_stores_one_proton_connection_whose_secret_is_the_bridge_password(room: World) -> None:
    full_login(room)
    listed = room.client.get("/api/connections").json()["connections"]
    (proton,) = [c for c in listed if c["kind"] == "proton"]
    opened = room.run(lambda: services.get(Connections).opened(proton["id"], room.home, room.alana))
    assert opened is not None and opened.secret == BRIDGE_PASSWORD


def test_nothing_typed_is_stored_and_the_bridge_password_only_sealed(room: World) -> None:
    room.client.post(ROOM, json={"label": LABEL, "username": USERNAME, "password": PASSWORD}, headers=ORIGIN)
    room.client.post(ROOM + "/two-factor", json={"label": LABEL, "code": CODE}, headers=ORIGIN)
    stored = dump(room.url)
    assert "proton" in stored, "control: the probe sees the connection's row"
    for typed in (USERNAME, PASSWORD, CODE, MAILBOX_PASSWORD, BRIDGE_PASSWORD):
        assert typed not in stored, f"{typed} is stored in the clear"


@pytest.mark.xfail(strict=True, reason="open question: only the keeper holds the pending login (the app keeps no state in a pod, "
                   "and a login's steps may reach either site), so the app relays a step out of order and the keeper's "
                   "Bridge refuses it")
def test_a_step_out_of_order_is_refused_and_never_reaches_the_keeper(room: World, keeper: FakeKeeperHttp) -> None:
    assert post(room, "/two-factor", code=CODE) in range(400, 500)
    assert keeper.steps == []


def test_a_login_the_keeper_refuses_stores_no_connection_and_does_not_echo_the_password(room: World, keeper: FakeKeeperHttp) -> None:
    keeper.script["/login"] = (401, {"error": "bad credentials"})
    got = room.client.post(ROOM, json={"label": LABEL, "username": USERNAME, "password": PASSWORD}, headers=ORIGIN)
    assert 400 <= got.status_code < 600 and got.status_code != 200
    assert PASSWORD not in got.text and USERNAME not in got.text
    assert room.client.get("/api/connections").json()["connections"] == []


def test_a_signed_out_caller_cannot_log_in(room: World, keeper: FakeKeeperHttp) -> None:
    room.client.cookies.clear()
    assert post(room, "", username=USERNAME, password=PASSWORD) == 401
    assert keeper.steps == []


def test_the_login_logs_no_password_code_username_bridge_password_or_address(room: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    full_login(room)
    logged = texts(caplog)
    assert "connections" in logged or "mail" in logged, "control: the login logged something"
    for secret in (USERNAME, PASSWORD, CODE, MAILBOX_PASSWORD, BRIDGE_PASSWORD, *ADDRESSES):
        assert secret not in logged, f"{secret} reached a log line"
