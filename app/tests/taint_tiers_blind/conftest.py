from collections.abc import Generator

import pytest
from ashley import services
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.proposals import Proposals
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from taint_tiers_blind_support import ActionJudge


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Proposals and the action judge start and end each test as their Null Objects."""
    services.unregister(Proposals)
    services.unregister(ActionJudge)
    services.unregister(OutsideRecord)
    yield
    services.unregister(Proposals)
    services.unregister(ActionJudge)
    services.unregister(OutsideRecord)
