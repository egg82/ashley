from collections.abc import Generator

import pytest
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from household_page_blind_support import People, app_client, as_, people_in


@pytest.fixture
def people(db_url: str) -> People:
    return people_in(db_url)


@pytest.fixture
def client(db_url: str, people: People) -> Generator[TestClient]:
    """The real app, signed in as Alana of `home`."""
    with app_client(db_url) as c:
        as_(c, people, "alana")
        yield c
