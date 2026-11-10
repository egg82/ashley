from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Connections and Sure start and end every test as Null Objects."""
    for interface in (Connections, Sure):
        services.unregister(interface)
    yield
    for interface in (Connections, Sure):
        services.unregister(interface)
