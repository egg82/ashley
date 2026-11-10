from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from mail_oauth_blind_fake_support import FakeGoogle
from mail_oauth_blind_support import People, app_client, as_, make_people

SERVICES = (Connections, ConnectionKinds)


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
def fake() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def client(db_url: str, people: People, fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    for c in app_client(db_url, fake, monkeypatch):
        as_(c, people, "alana")
        unlisted = tuple(replace(k, resources=None) for k in services.get(ConnectionKinds).all())
        services.register(ConnectionKinds, ConnectionKinds(unlisted))   # this suite is about tokens, not what they reach
        yield c


@pytest.fixture
def unconfigured(db_url: str, people: People, fake: FakeGoogle, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    for c in app_client(db_url, fake, monkeypatch, configured=False):
        as_(c, people, "alana")
        yield c
