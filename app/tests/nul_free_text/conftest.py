from collections.abc import Generator

import pytest
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from nul_free_text_support import app_client, person_in


@pytest.fixture
def client(db_url: str) -> Generator[TestClient]:
    """The real app, signed in as Alana of `home`."""
    with app_client(db_url, person_in(db_url)) as c:
        yield c
