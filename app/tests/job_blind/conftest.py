from collections.abc import Generator

import pytest
from ashley import services
from ashley.errands.errands import Errands
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """The locator is cleared by the root conftest; this keeps Errands unregistered across a test."""
    services.unregister(Errands)
    yield
    services.unregister(Errands)
