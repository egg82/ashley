from collections.abc import Generator

import pytest
from ashley import services
from ashley.codehost.host import CodeHost
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.home_assistant.homes import Homes
from ashley.sure.client import Sure
from connection_kinds_blind_support import Fakes, People, app_client, as_, make_people
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient

SERVICES = (Connections, ConnectionKinds, Sure, Homes, CodeHost)


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
def fakes() -> Fakes:
    return Fakes()


@pytest.fixture
def client(db_url: str, people: People, fakes: Fakes) -> Generator[TestClient]:
    for c in app_client(db_url, fakes):
        as_(c, people, "alana")
        yield c
