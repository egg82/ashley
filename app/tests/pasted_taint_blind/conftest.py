from collections.abc import Generator

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def conversations_unwired() -> Generator[None]:
    yield
    services.unregister(Conversations)
