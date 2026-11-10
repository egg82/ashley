from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.people.people import People
from ashley.senses.deposits import Deposits
from ashley.senses.proposals import Proposals
from ashley.senses.wakes import Wakes
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

SERVICES = (Deposits, Proposals, Wakes, Connections, Sure, People)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
