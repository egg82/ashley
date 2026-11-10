from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.resources import ConnectionResources
from ashley.mail.mailbox import Mailbox
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

SERVICES = (Mailbox, ConnectionResources, Watches)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
