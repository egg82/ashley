"""What protects the control port between the app and Bridge's pod: the certificate the app made for the pod, kept in the
shared record, is the only one the app trusts and the one the keeper serves under, so a typed password crosses encrypted
and only to that pod; the app reaches the pod only by https addresses; and a login reaches it from a site whose cluster
holds no Secret for it, trying each site's address in order and moving on only when none is listening."""

import asyncio
import socket
import threading
from collections.abc import Generator
from pathlib import Path

import httpx2
import pytest
from ashley.mail import config, proton_pod, proton_tls
from ashley.mail.proton_bridge import BridgeUnavailable, KeeperAccess
from ashley.mail.proton_login import Ask
from ashley.mail.proton_login_http import KeeperLogin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from keeper_link import LoginEvent
from keeper_serve import serve, server_context
from mail_bridge_support import bridge_on
from mail_keeper_support import TOKEN, Rig, make_keychain, rig, FakeApp


def write_pair(directory: Path, pair: dict[str, str]) -> None:
    directory.mkdir()
    (directory / "tls.crt").write_text(pair[proton_tls.CERT_KEY])
    (directory / "tls.key").write_text(pair[proton_tls.KEY_KEY])


@pytest.fixture
def keeper(tmp_path: Path) -> Generator[tuple[Rig, int, dict[str, str]]]:
    made = tmp_path / "earlier"
    made.mkdir()
    r = rig(tmp_path / "home", FakeApp(1, b"v", make_keychain(made)))
    r.home.mkdir()
    r.keeper.boot()
    pair = proton_tls.make()
    write_pair(tmp_path / "tls", pair)
    server = serve(r.keeper, TOKEN, 0, "127.0.0.1", server_context(str(tmp_path / "tls")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield r, server.server_address[1], pair
    server.shutdown()
    server.server_close()


def refused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def login_through(db_url: str, ports: list[int], access: dict[str, str]) -> object:
    """A login relayed by a pod whose cluster has no Secret: the record alone carries the token and certificate."""
    async with bridge_on(db_url) as bridge:
        grant = KeeperAccess(access[proton_pod.TOKEN_KEY], access[proton_tls.CERT_KEY])
        assert await bridge.raise_epoch(0, "birch", b"x" * 32, grant) == 1
        login = KeeperLogin(tuple(f"https://127.0.0.1:{p}" for p in ports), bridge, config.load().timeout_s)
        return await login.begin("alana", "typed-password")


def test_the_login_reaches_the_keeper_over_tls_under_the_certificate_in_the_record(
        db_url: str, keeper: tuple[Rig, int, dict[str, str]]) -> None:
    r, port, pair = keeper
    r.bridge.logins = [LoginEvent("tfa")]
    assert asyncio.run(login_through(db_url, [port], {proton_pod.TOKEN_KEY: TOKEN, **pair})) == Ask("two_factor")


def test_a_keeper_that_serves_another_certificate_is_not_trusted_and_gets_no_password(
        db_url: str, keeper: tuple[Rig, int, dict[str, str]]) -> None:
    r, port, _ = keeper
    r.bridge.logins = [LoginEvent("tfa")]
    with pytest.raises(BridgeUnavailable):
        asyncio.run(login_through(db_url, [port], {proton_pod.TOKEN_KEY: TOKEN, **proton_tls.make()}))
    assert r.bridge.logins == [LoginEvent("tfa")]


def test_an_address_that_refuses_connections_is_passed_over_for_the_next(
        db_url: str, keeper: tuple[Rig, int, dict[str, str]]) -> None:
    r, port, pair = keeper
    r.bridge.logins = [LoginEvent("tfa")]
    got = asyncio.run(login_through(db_url, [refused_port(), port], {proton_pod.TOKEN_KEY: TOKEN, **pair}))
    assert got == Ask("two_factor")


def test_no_address_listening_is_the_bridge_being_unavailable(db_url: str) -> None:
    with pytest.raises(BridgeUnavailable):
        asyncio.run(login_through(db_url, [refused_port(), refused_port()],
                                  {proton_pod.TOKEN_KEY: TOKEN, **proton_tls.make()}))


def test_an_address_that_answers_with_a_wrong_certificate_is_not_passed_over(
        db_url: str, tmp_path: Path, keeper: tuple[Rig, int, dict[str, str]]) -> None:
    r, port, _ = keeper
    stale = proton_tls.make()
    write_pair(tmp_path / "stale", stale)
    other = serve(r.keeper, TOKEN, 0, "127.0.0.1", server_context(str(tmp_path / "stale")))
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        r.bridge.logins = [LoginEvent("tfa")]
        with pytest.raises(BridgeUnavailable):
            asyncio.run(login_through(db_url, [port, other.server_address[1]], {proton_pod.TOKEN_KEY: TOKEN, **stale}))
    finally:
        other.shutdown()
        other.server_close()
    assert r.bridge.logins == [LoginEvent("tfa")]


def test_an_http_answer_from_the_first_address_is_the_answer(
        db_url: str, keeper: tuple[Rig, int, dict[str, str]]) -> None:
    r, port, pair = keeper
    r.bridge.logins = [LoginEvent("tfa")]
    with pytest.raises(BridgeUnavailable, match="401|403"):
        asyncio.run(login_through(db_url, [port], {proton_pod.TOKEN_KEY: "wrong-token", **pair}))
    assert r.bridge.logins == [LoginEvent("tfa")]


def test_the_control_port_does_not_answer_plain_http(keeper: tuple[Rig, int, dict[str, str]]) -> None:
    _, port, _ = keeper
    with pytest.raises(httpx2.HTTPError):
        httpx2.post(f"http://127.0.0.1:{port}/login", json={"username": "a", "password": "b"}, timeout=5)


def test_the_pod_mounts_the_secrets_certificate_and_holds_no_key_in_its_spec() -> None:
    manifest = proton_pod.manifest(3, "registry.test/b@sha256:" + "c" * 64, "https://ashley.test", config.load())
    spec = manifest["spec"]
    assert {"name": "tls", "secret": {"secretName": "mail-bridge-3", "defaultMode": 0o440, "items": [
        {"key": "tls.crt", "path": "tls.crt"}, {"key": "tls.key", "path": "tls.key"}]}} in spec["volumes"]
    mounts = {m["name"]: m for m in spec["containers"][0]["volumeMounts"]}
    env = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
    assert mounts["tls"]["readOnly"] and env["BRIDGE_TLS_DIR"] == mounts["tls"]["mountPath"]
    assert "PRIVATE KEY" not in str(spec)


@pytest.mark.parametrize("name", ["mail_bridge_app_url", "mail_bridge_keeper_url"])
def test_a_plain_http_address_for_either_end_is_refused(name: str) -> None:
    urls = {"mail_bridge_app_url": "https://ashley.test", "mail_bridge_keeper_url": "https://keeper.test:8080"}
    base = dict(database_url="x", build_version="t", etcd_url="http://e:2379", site="birch", sandbox_token_file="t",
                sandbox_ca_file="c", connections_key="k", mail_bridge_image="i", mail_bridge_namespace="n")
    Settings(**base, **urls)
    with pytest.raises(ValueError, match="https"):
        Settings(**base, **{**urls, name: "http://plain.test"})


def test_the_keeper_addresses_are_a_list_in_order_and_every_one_must_be_https() -> None:
    base = dict(database_url="x", build_version="t", etcd_url="http://e:2379", site="birch", sandbox_token_file="t",
                sandbox_ca_file="c", connections_key="k", mail_bridge_image="i", mail_bridge_namespace="n",
                mail_bridge_app_url="https://ashley.test")
    two = "https://10.99.0.10:8080/, https://10.99.0.20:8080"
    assert Settings(**base, mail_bridge_keeper_url=two).mail_bridge_keeper_urls == (
        "https://10.99.0.10:8080", "https://10.99.0.20:8080")
    for bad in (two + ",http://plain.test:8080", two + ","):
        with pytest.raises(ValueError, match="https"):
            Settings(**base, mail_bridge_keeper_url=bad)
