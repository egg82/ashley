from conn_settings_blind_support import People, app_client, as_, people_in
from fastapi.testclient import TestClient
from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.home_assistant.homes import Homes
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.proposals import Proposals
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

_WIRED = (Connections, Sure, Homes, OutsideRecord, Proposals)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service this suite touches starts and ends each test as its Null Object."""
    for interface in _WIRED:
        services.unregister(interface)
    yield
    for interface in _WIRED:
        services.unregister(interface)


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    with app_client(db_url, people) as c:
        as_(c, people, "alana")
        yield c
