from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.resources import ConnectionResources
from ashley.mail.mailbox import Mailbox
from ashley.mail.proton_bridge import ProtonBridge
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from mail_proton_blind_bridge_support import FakeBridge
from mail_proton_blind_support import ALANA_ADDRESS, Box, World, app_client, build_world

SERVICES = (Connections, ConnectionKinds, ConnectionResources, ProtonBridge, Mailbox)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)


@pytest.fixture
def bridge() -> Generator[FakeBridge]:
    fake = FakeBridge("starttls")
    yield fake
    fake.stop()


@pytest.fixture
def client(db_url: str, bridge: FakeBridge) -> Generator[TestClient]:
    yield from app_client(db_url, bridge)


@pytest.fixture
def world(db_url: str, bridge: FakeBridge, client: TestClient) -> World:
    return build_world(db_url, bridge, client)


@pytest.fixture
def alana(world: World) -> Box:
    """Alana's synced Proton mailbox, with nothing in it yet."""
    return world.box(ALANA_ADDRESS)
