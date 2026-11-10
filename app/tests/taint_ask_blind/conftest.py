from collections.abc import Generator

import pytest
from ashley import services
from ashley.senses.proposals import Proposals
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Proposals starts and ends each test as its Null Object."""
    services.unregister(Proposals)
    yield
    services.unregister(Proposals)
