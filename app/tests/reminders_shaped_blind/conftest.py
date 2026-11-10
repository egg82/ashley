import importlib
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.outbox import Outbox
from ashley.channels.push.subscriptions import Subscriptions
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.initiative.initiative import Initiative
from ashley.inference.inference import Inference
from ashley.live.live import Live
from ashley.people.people import People
from ashley.senses.deposits import Deposits
from ashley.senses.proposals import Proposals
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Tools
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

sys.path.insert(0, str(Path(__file__).parents[1] / "contract"))
_inflight = importlib.import_module("contract.test_inflight_resume")
system = _inflight.system
world = _inflight.world

SERVICES = (Wakes, Deposits, Proposals, Initiative, Workshop, Devices, People, Inference, Tools, Outbox, Conversations, InFlight, Presence, Live,
            Subscriptions)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these suites register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
