from collections.abc import Generator

import pytest
from ashley import services
from ashley.runs.runs import Runs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from rhb_support import system as system


@pytest.fixture(autouse=True)
def runs_unwired() -> Generator[None]:
    """Runs starts and ends every test as its Null Object, as the rest of the suite's services do."""
    services.unregister(Runs)
    yield
    services.unregister(Runs)


__all__ = ["system", "db_url", "migrated_template"]
