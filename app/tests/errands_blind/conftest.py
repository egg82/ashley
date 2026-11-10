from collections.abc import Generator

import pytest
from ashley import services
from ashley.errands.errands import Errands
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Errands starts and ends each test as its Null Object."""
    services.unregister(Errands)
    yield
    services.unregister(Errands)
