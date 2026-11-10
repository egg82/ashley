from collections.abc import Generator

import pytest
from hypothesis import find
from hypothesis import strategies as st

from contract.conversations_support import db_url as db_url, migrated_template as migrated_template


@pytest.fixture(scope="session", autouse=True)
def hypothesis_started() -> Generator[None]:
    """Hypothesis's one-time start-up in each worker, paid here rather than by whichever property test runs first."""
    find(st.integers(), lambda _: True)
    yield
