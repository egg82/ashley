"""The warm look pod's keeper and Proton Bridge's keeper run under whichever `Lease` is wired: etcd's, with the same
lease names as ever, or Postgres's where there is no etcd, and their settings no longer ask for etcd."""

import asyncio
import base64
import os
from collections.abc import Generator
from pathlib import Path

import pytest
import httpx2
from ashley import services, wiring_bridge, wiring_sandbox, wiring_singletons
from ashley.connections.kinds import ConnectionKinds
from ashley.db.database import Database
from ashley.looks import warm_pod
from ashley.looks.looker import Looker
from ashley.looks.browser import PageBrowser
from ashley.mail import proton_bridge_job
from ashley.mail.proton_bridge import ProtonBridge
from ashley.mail.proton_bridge_job import BridgeKeeping, Keeping
from ashley.mail.proton_login import ProtonLogin
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.lease import Body, Lease
from ashley.referee.postgres_lease import PostgresLease
from ashley.runs.kube_api import KubeApi
from ashley.settings import Settings
from ashley.wiring import CONNECTION_KINDS

LOOK = "registry.example/look@sha256:" + "e" * 64
BRIDGE_IMAGE = "registry.example/ashley-mail-bridge@sha256:" + "d" * 64
KEY = base64.b64encode(os.urandom(32)).decode()
URL = "postgresql://nobody@127.0.0.1:1/none"
BASE = {"database_url": URL, "build_version": "t", "sandbox_token_file": "/token", "sandbox_ca_file": "/ca",
        "files_endpoints": "http://nas.test", "files_bucket": "b", "files_access_key": "k", "files_secret_key": "s",
        "files_link_key": "l" * 40, "connections_key": KEY, "look_image": LOOK, "look_app_url": "http://app:8080",
        "look_warm_url": "http://ashley-look-warm.ashley-sandbox.svc:8080", "mail_bridge_image": BRIDGE_IMAGE,
        "mail_bridge_namespace": "ashley-mail", "mail_bridge_app_url": "https://ashley.example",
        "mail_bridge_keeper_url": "https://mail-bridge.ashley-mail.svc:8080"}
ETCD = {"etcd_url": "http://127.0.0.1:1", "site": "willow"}
STARTED: list[tuple[str, str]] = []


class RecordingPostgres(PostgresLease):
    async def run(self, name: str, body: Body) -> None:
        STARTED.append((type(self).__name__, name))


async def _record_etcd(self: EtcdLease, name: str, body: Body) -> None:
    STARTED.append((type(self).__name__, f"{name}|gated={self._gated}"))


@pytest.fixture
def clean(tmp_path: Path) -> Generator[KubeApi]:
    STARTED.clear()
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    yield KubeApi(httpx2.AsyncClient(base_url="https://kube.test"), str(tmp_path / "token"))
    for interface in (Lease, Looker, PageBrowser, ProtonBridge, ProtonLogin, Keeping, Database, ConnectionKinds):
        services.unregister(interface)


def wire_pods(settings: Settings, api: KubeApi) -> None:
    wiring_sandbox.wire_looker(settings, api, [])
    wiring_bridge.wire_mail_bridge(settings, api)


def run_all(settings: Settings) -> None:
    async def go() -> None:
        await asyncio.gather(*wiring_singletons.singletons(settings))

    asyncio.run(go())


def test_without_etcd_the_settings_start_and_both_keepers_run_on_the_postgres_lease(clean: KubeApi) -> None:
    settings = Settings(**BASE)
    wire_pods(settings, clean)
    services.register(Lease, RecordingPostgres(URL))
    run_all(settings)
    assert ("RecordingPostgres", warm_pod.NAME) in STARTED
    assert ("RecordingPostgres", proton_bridge_job.NAME) in STARTED
    keeping = services.get(Keeping)
    assert isinstance(keeping, BridgeKeeping) and keeping._site == wiring_bridge.LOCAL_SITE


def test_with_etcd_the_same_lease_names_and_keepers_are_wired(clean: KubeApi, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(**BASE, **ETCD)
    wire_pods(settings, clean)
    wiring_singletons.wire_lease(settings)
    assert type(services.get(Lease)) is EtcdLease
    monkeypatch.setattr(EtcdLease, "run", _record_etcd)
    run_all(settings)
    assert ("EtcdLease", f"{warm_pod.NAME}@willow|gated=False") in STARTED
    assert ("EtcdLease", f"{proton_bridge_job.NAME}|gated=True") in STARTED
    keeping = services.get(Keeping)
    assert isinstance(keeping, BridgeKeeping) and keeping._site == "willow"


def test_without_etcd_the_postgres_lease_is_wired_for_these_settings(clean: KubeApi) -> None:
    wiring_singletons.wire_lease(Settings(**BASE))
    assert type(services.get(Lease)) is PostgresLease
