from collections.abc import Generator

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.inference.inference import Inference
from ashley.people.people import People
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.proposals import Proposals
from ashley.tools.action_judge import ActionJudge
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

WIRED = (Proposals, ActionJudge, OutsideRecord, Inference, Conversations, People)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service the judge suites wire starts and ends each test as its Null Object."""
    for interface in WIRED:
        services.unregister(interface)
    yield
    for interface in WIRED:
        services.unregister(interface)
