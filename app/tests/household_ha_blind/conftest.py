from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.home_assistant.homes import Homes
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Connections, Sure and Homes start and end every test as Null Objects."""
    for interface in (Connections, Sure, Homes):
        services.unregister(interface)
    yield
    for interface in (Connections, Sure, Homes):
        services.unregister(interface)
