from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.resources import ConnectionResources
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from mail_changes_blind_fake_support import FakeGmail
from mail_changes_blind_support import World, app_client, build_world, stock

SERVICES = (Connections, ConnectionKinds, ConnectionResources)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)


@pytest.fixture
def fake() -> FakeGmail:
    return FakeGmail()


@pytest.fixture
def client(db_url: str, fake: FakeGmail, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    yield from app_client(db_url, fake, monkeypatch)


@pytest.fixture
def world(db_url: str, fake: FakeGmail, client: TestClient) -> World:
    return build_world(db_url, fake, client)


@pytest.fixture
def stocked(world: World) -> World:
    """A world with Alana's own Google connection (change scope) and four messages in his mailbox."""
    stock(world)
    world.connect()
    return world
