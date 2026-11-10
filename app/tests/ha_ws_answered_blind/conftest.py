from collections.abc import Generator

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from ha_ws_answered_support import World, ha as ha, make_world, stand_in as stand_in


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    for interface in (Connections, ConnectionKinds):
        services.unregister(interface)
    yield
    for interface in (Connections, ConnectionKinds):
        services.unregister(interface)


@pytest.fixture
def world(db_url: str) -> World:
    return make_world(db_url)
