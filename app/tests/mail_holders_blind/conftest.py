from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.resources import ConnectionResources
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from mail_holders_blind_support import Boxes, People, app_client, as_, make_people

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
def people(db_url: str) -> People:
    return make_people(db_url)


@pytest.fixture
def boxes() -> Boxes:
    return Boxes()


@pytest.fixture
def client(db_url: str, people: People, boxes: Boxes) -> Generator[TestClient]:
    for c in app_client(db_url, boxes):
        as_(c, people, "alana")
        yield c
