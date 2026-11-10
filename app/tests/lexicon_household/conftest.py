from collections.abc import Generator

import pytest
from ashley import services
from ashley.channels.lexicons import Lexicons
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def lexicons_unwired() -> Generator[None]:
    services.unregister(Lexicons)
    yield
    services.unregister(Lexicons)
