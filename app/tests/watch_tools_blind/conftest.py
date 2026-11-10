from collections.abc import Generator

import pytest

from ashley import services
from ashley.connections.connections import Connections
from ashley.people.people import People
from ashley.senses.proposals import Proposals
from ashley.tools.tools import Tools
from ashley.watches.watches import Watches

SERVICES = (People, Connections, Proposals, Tools, Watches)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
