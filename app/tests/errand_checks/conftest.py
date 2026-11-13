"""The reminder suite's `world` (two pods over one database), loaded with its directory on the path, since its modules
import their siblings by bare name; its `stack` is the `wakes` runner over the real turn loop."""

import importlib
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.push.subscriptions import Subscriptions
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.initiative.initiative import Initiative
from ashley.live.live import Live
from ashley.people.people import People
from ashley.senses.presence import Presence
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Tools
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

sys.path.insert(0, str(Path(__file__).parents[1] / "reminders_blind"))
_world = importlib.import_module("rb_world")
system = _world.system
world = _world.world

SERVICES = (Wakes, Initiative, Workshop, People, Inference, Tools, Outbox, Conversations, InFlight, Presence, Live,
            Subscriptions)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service these tests register starts and ends each test as its Null Object."""
    for interface in SERVICES:
        services.unregister(interface)
    yield
    for interface in SERVICES:
        services.unregister(interface)
