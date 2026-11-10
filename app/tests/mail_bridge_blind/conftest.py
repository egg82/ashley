from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.mail.proton_bridge import ProtonBridge
from ashley.mail.proton_login import ProtonLogin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from mail_bridge_blind_keeper_support import FakeApp, Keeper
from mail_bridge_blind_kube_support import FakeKube
from mail_bridge_blind_support import ALIASES, World, app_client, make_world

SERVICES = (Connections, ConnectionKinds, ProtonBridge, ProtonLogin)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    ALIASES.clear()
    yield
    for interface in SERVICES:
        services.unregister(interface)


@pytest.fixture
def client(db_url: str) -> Generator[TestClient]:
    yield from app_client(db_url)


@pytest.fixture
def world(db_url: str, client: TestClient) -> World:
    return make_world(db_url, client)


@pytest.fixture
def kube() -> FakeKube:
    return FakeKube()


@pytest.fixture
def fake_app() -> Generator[FakeApp]:
    app = FakeApp().start()
    yield app
    app.stop()


@pytest.fixture
def keeper_for(tmp_path: Path) -> Generator[Callable[..., Keeper]]:
    made: list[Keeper] = []

    def start(app: FakeApp, refresh: bool = True, **env: str) -> Keeper:
        keeper = Keeper(tmp_path, app, refresh, **env)
        made.append(keeper)
        return keeper

    yield start
    for keeper in made:
        keeper.close()
