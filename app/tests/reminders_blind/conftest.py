from collections.abc import Generator

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.push.subscriptions import Subscriptions
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.initiative.initiative import Initiative
from ashley.inference.inference import Inference
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Tools
from ashley.workshop.workshop import Workshop
from rb_world import system as system, world as world
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from ashley.channels.outbox import Outbox
from rb_support import Home
from ashley.live.live import Live

SERVICES = (Wakes, Initiative, Workshop, Devices, People, Inference, Tools, Outbox, Conversations, InFlight, Presence, Live, Subscriptions)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)


@pytest.fixture
def home(db_url: str) -> Home:
    return Home(db_url)
