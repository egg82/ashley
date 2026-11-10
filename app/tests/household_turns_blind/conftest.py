from collections.abc import Generator

import pytest
from ashley import services
from ashley.channels.outbox import Outbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.initiative.initiative import Initiative
from ashley.inference.inference import Inference
from ashley.memory.memory import Memory
from ashley.people.people import People
from ashley.runs.runs import Runs
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Tools
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

SERVICES = (Wakes, Initiative, Workshop, People, Inference, Tools, Outbox, Conversations, InFlight, Presence, Memory, Runs)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
