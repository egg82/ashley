import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.workshop.workshop import Workshop

sys.path.append(str(Path(__file__).parents[1] / "contract"))  # the look-up contract support imports its siblings bare


@pytest.fixture(autouse=True)
def locator_left_empty() -> Generator[None]:
    """The tests register a Workshop and Conversations; none leaks to the next test in the worker."""
    yield
    services.unregister(Workshop)
    services.unregister(Conversations)
