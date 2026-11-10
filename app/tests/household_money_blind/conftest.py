from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.memory.memory import Memory
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in (Connections, Sure, Memory):
        services.unregister(interface)
    yield
    for interface in (Connections, Sure, Memory):
        services.unregister(interface)
