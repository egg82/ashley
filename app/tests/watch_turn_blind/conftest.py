import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge
from ashley.initiative.initiative import Initiative
from ashley.inference.inference import Inference
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Tools
from ashley.workshop.workshop import Workshop

sys.path.insert(0, str(Path(__file__).parents[1] / "wakes_blind"))

from wb_world import system as system, world as world
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from ashley.channels.outbox import Outbox
from ashley.live.live import Live
from ashley.watches.watches import Watches

SERVICES = (Wakes, Initiative, Workshop, Devices, People, Inference, Tools, Outbox, Conversations, InFlight, Presence,
            Live, Watches, Bridge, Connections)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
