from collections.abc import Generator

import pytest
from ashley import services
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Watches starts and ends each test as its Null Object."""
    services.unregister(Watches)
    yield
    services.unregister(Watches)
