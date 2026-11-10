from collections.abc import Generator

import pytest
from ashley import services
from connections_by_id_blind_support import SERVICES, Checks, People, app_client, as_, make_people
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient


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
def checks() -> Checks:
    return Checks()


@pytest.fixture
def client(db_url: str, people: People, checks: Checks) -> Generator[TestClient]:
    for c in app_client(db_url, checks):
        as_(c, people, "alana")
        yield c


@pytest.fixture
def keyless(db_url: str, people: People, checks: Checks) -> Generator[TestClient]:
    for c in app_client(db_url, checks, key=""):
        as_(c, people, "alana")
        yield c
