"""Proton Bridge is wired only with all four of its settings and what holds its lease; wired, the Proton kind is offered, the
record, login and upkeep are registered and a singleton keeps the pod; unwired, none of that is."""

import base64
import os
from collections.abc import Generator
from pathlib import Path

import httpx2
import pytest
from ashley import services, wiring_bridge, wiring_singletons
from ashley.connections.kinds import ConnectionKinds
from ashley.mail.proton_bridge import NullProtonBridge, ProtonBridge
from ashley.mail.proton_bridge_job import BridgeKeeping, Keeping
from ashley.mail.proton_login import ProtonLogin
from ashley.mail.proton_login_http import KeeperLogin
from ashley.runs.kube_api import KubeApi
from ashley.settings import Settings, from_env
from ashley.wiring import configured_kinds

IMAGE = "registry.example/ashley-mail-bridge@sha256:" + "d" * 64
KEY = base64.b64encode(os.urandom(32)).decode()
BASE = {"database_url": "postgresql://x", "build_version": "t", "sandbox_token_file": "/token", "sandbox_ca_file": "/ca",
        "etcd_url": "http://127.0.0.1:1", "site": "birch", "connections_key": KEY}
BRIDGE = {"mail_bridge_image": IMAGE, "mail_bridge_namespace": "ashley-mail", "mail_bridge_app_url": "https://ashley.example",
          "mail_bridge_keeper_url": "https://mail-bridge.ashley-mail.svc:8080"}


@pytest.fixture
def api(tmp_path: Path) -> Generator[KubeApi]:
    yield KubeApi(httpx2.AsyncClient(base_url="https://kube.test"), str(tmp_path / "token"))
    for interface in (ProtonBridge, ProtonLogin, Keeping):
        services.unregister(interface)


def test_the_four_settings_come_together() -> None:
    for left_out in BRIDGE:
        with pytest.raises(ValueError, match="must be set together"):
            Settings(**BASE, **{k: v for k, v in BRIDGE.items() if k != left_out})
    assert Settings(**BASE, **BRIDGE).mail_bridge_image == IMAGE


@pytest.mark.parametrize("missing", ["sandbox_token_file", "etcd_url", "site", "connections_key"])
def test_the_image_needs_the_sandbox_the_lease_the_site_and_the_key(missing: str) -> None:
    base = {**BASE, "sandbox_ca_file": "/ca", missing: ""}
    with pytest.raises(ValueError, match="MAIL_BRIDGE_IMAGE needs|SANDBOX_TOKEN_FILE needs"):
        Settings(**base, **BRIDGE)


def test_the_settings_come_from_the_environment_without_a_trailing_slash() -> None:
    env = {k.upper(): str(v) for k, v in {**BASE, **BRIDGE}.items()}
    got = from_env({**env, "MAIL_BRIDGE_KEEPER_URL": BRIDGE["mail_bridge_keeper_url"] + "/"})
    assert got.mail_bridge_keeper_urls == (BRIDGE["mail_bridge_keeper_url"],)


def test_wired_the_proton_kind_is_offered_and_a_singleton_keeps_the_pod(api: KubeApi) -> None:
    settings = Settings(**BASE, **BRIDGE)
    services.register(ConnectionKinds, ConnectionKinds(configured_kinds(settings)))
    bare = wiring_singletons.singletons(Settings(database_url="x", build_version="t", etcd_url=BASE["etcd_url"]))
    wiring_bridge.wire_mail_bridge(settings, api)
    assert "proton" in [k.name for k in services.get(ConnectionKinds).offered(1)]
    assert not isinstance(services.get(ProtonBridge), NullProtonBridge)
    assert isinstance(services.get(ProtonLogin), KeeperLogin) and isinstance(services.get(Keeping), BridgeKeeping)
    running = wiring_singletons.singletons(settings)
    for coroutine in [*bare, *running]:
        coroutine.close()
    assert len(running) - len(bare) == 1


def test_unwired_the_proton_kind_is_not_offered_and_nothing_keeps_a_pod() -> None:
    unwired = Settings(database_url="x", build_version="t", etcd_url=BASE["etcd_url"])
    services.register(ConnectionKinds, ConnectionKinds(configured_kinds(unwired)))
    assert services.get(ConnectionKinds).get("proton") is not None
    assert "proton" not in [k.name for k in services.get(ConnectionKinds).offered(1)]
    assert "proton" not in [k.name for k in services.get(ConnectionKinds).of_port("mail")]
    running = wiring_singletons.singletons(unwired)
    for coroutine in running:
        coroutine.close()
    assert not isinstance(services.get(Keeping), BridgeKeeping)


def test_a_floating_image_is_refused(api: KubeApi) -> None:
    loose = Settings(**BASE, **{**BRIDGE, "mail_bridge_image": "registry.example/ashley-mail-bridge:latest"})
    with pytest.raises(ValueError, match="pinned"):
        wiring_bridge.wire_mail_bridge(loose, api)
