from collections.abc import Generator

import pytest
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from sb_rig import Rig, rig


@pytest.fixture
def app(db_url: str) -> Generator[Rig]:
    with rig(db_url) as made:
        yield made
