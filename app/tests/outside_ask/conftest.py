from collections.abc import Generator

import pytest
from ashley import services
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.proposals import Proposals
from outside_record_support import MemoryRecord
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Proposals starts and ends each test as its Null Object; the outside record is a fresh one in memory."""
    services.unregister(Proposals)
    services.register(OutsideRecord, MemoryRecord())
    yield
    services.unregister(Proposals)
    services.unregister(OutsideRecord)
