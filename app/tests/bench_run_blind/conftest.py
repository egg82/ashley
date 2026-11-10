from collections.abc import Generator

import pytest
from ashley import services
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from hypothesis import find
from hypothesis import strategies as st

from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(autouse=True)
def sandbox_unwired() -> Generator[None]:
    """The Sandbox and Runs start and end every test as Null Objects."""
    for interface in (Sandbox, Runs):
        services.unregister(interface)
    yield
    for interface in (Sandbox, Runs):
        services.unregister(interface)


@pytest.fixture(scope="session", autouse=True)
def hypothesis_started() -> Generator[None]:
    find(st.integers(), lambda _: True)
    yield
