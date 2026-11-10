from collections.abc import Generator

import pytest
from ashley import services
from ashley.db.database import Database
from ashley.files.store import ObjectStore
from ashley.live.live import Live
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

WIRED = (Sandbox, Runs, Workshop, ObjectStore, Live, Database)


@pytest.fixture(autouse=True)
def services_unwired() -> Generator[None]:
    """Every service starts and ends each test as its Null Object."""
    for interface in WIRED:
        services.unregister(interface)
    yield
    for interface in WIRED:
        services.unregister(interface)
