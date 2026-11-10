"""The memory routes with a members fact: each member sees it, nobody else does, a private money fact moved to the
household becomes `members` (never `shared`), and a members fact moved to mine becomes private."""

from collections.abc import Generator

import pytest
from ashley.api.models import MemoryFact, MemoryFactsResponse
from ashley.api.person import person_signed_in
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from hm_support import TEXT, Home, make_home

PUBLIC = "https://ashley.test"


class As:
    def __init__(self, home: Home) -> None:
        self.home = home
        self.who = home.alana
        self.names = {home.alana: ("Alana", home.id), home.elodie: ("Elodie", home.id), home.mia: ("Mia", home.other)}

    def person(self) -> SignedIn:
        name, household = self.names[self.who]
        return SignedIn(1, Person(self.who, household, name))


@pytest.fixture
def home(db_url: str) -> Home:
    return make_home(db_url)


@pytest.fixture
def signed(home: Home) -> As:
    return As(home)


@pytest.fixture
def client(home: Home, signed: As) -> Generator[TestClient]:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = signed.person
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        yield c


def listed(client: TestClient) -> dict[int, MemoryFact]:
    got = client.get("/api/memory/facts")
    assert got.status_code == 200
    return {f.id: f for f in MemoryFactsResponse.model_validate(got.json()).items}


def test_each_member_is_shown_a_members_fact_and_another_household_is_not(client: TestClient, home: Home, signed: As) -> None:
    fact = home.raw(TEXT, None, "members", about=home.alana)
    for member in (home.alana, home.elodie):
        signed.who = member
        seen = listed(client)
        assert fact in seen and seen[fact].visibility == "members" and seen[fact].owner is None
        assert seen[fact].text == TEXT
    signed.who = home.mia
    assert listed(client) == {}


def test_a_private_money_fact_moved_to_the_household_becomes_members_not_shared(client: TestClient, home: Home,
                                                                              signed: As) -> None:
    fact = home.raw(TEXT, home.alana, "private")
    signed.who = home.elodie
    assert fact not in listed(client)
    signed.who = home.alana
    moved = client.post(f"/api/memory/facts/{fact}/moves", json={"to": "household"})
    assert moved.status_code == 201, moved.text
    now = MemoryFact.model_validate(moved.json())
    assert (now.visibility, now.owner, now.text, now.kind) == ("members", None, TEXT, "finance")
    assert scalar(home.url, "SELECT count(*) FROM facts WHERE visibility = 'shared'") == 0
    assert scalar(home.url, "SELECT count(*) FROM facts WHERE valid_to IS NULL AND visibility = 'members' "
                            "AND owner_id IS NULL") == 1
    signed.who = home.elodie
    assert [f.visibility for f in listed(client).values()] == ["members"]


def test_a_members_fact_moved_to_mine_becomes_private_to_the_mover(client: TestClient, home: Home, signed: As) -> None:
    fact = home.raw(TEXT, None, "members")
    signed.who = home.elodie
    moved = client.post(f"/api/memory/facts/{fact}/moves", json={"to": "mine"})
    assert moved.status_code == 201, moved.text
    now = MemoryFact.model_validate(moved.json())
    assert now.visibility == "private" and now.owner is not None and now.owner.name == "Elodie"
    assert scalar(home.url, "SELECT count(*) FROM facts WHERE valid_to IS NULL AND visibility = 'private' "
                            "AND owner_id = %s", (home.elodie,)) == 1
    assert scalar(home.url, "SELECT count(*) FROM facts WHERE valid_to IS NULL AND visibility = 'members'") == 0
    signed.who = home.alana
    assert listed(client) == {}


def test_a_private_fact_that_is_not_money_moved_to_the_household_is_still_shared(client: TestClient, home: Home,
                                                                              signed: As) -> None:
    fact = home.raw("The wifi password is on the fridge", home.alana, "private", kind="home")
    moved = client.post(f"/api/memory/facts/{fact}/moves", json={"to": "household"})
    assert moved.status_code == 201, moved.text
    assert MemoryFact.model_validate(moved.json()).visibility == "shared"


def test_any_member_may_forget_a_members_fact_through_the_route(client: TestClient, home: Home, signed: As) -> None:
    fact = home.raw(TEXT, None, "members", about=home.alana)
    signed.who = home.elodie
    assert client.delete(f"/api/memory/facts/{fact}").status_code == 200
    signed.who = home.alana
    assert listed(client) == {}
    assert scalar(home.url, "SELECT count(*) FROM facts") == 0


def test_another_household_cannot_move_or_forget_it(client: TestClient, home: Home, signed: As) -> None:
    fact = home.raw(TEXT, None, "members", about=home.alana)
    signed.who = home.mia
    assert client.post(f"/api/memory/facts/{fact}/moves", json={"to": "mine"}).status_code == 404
    assert client.delete(f"/api/memory/facts/{fact}").status_code == 404
    assert scalar(home.url, "SELECT count(*) FROM facts WHERE visibility = 'members'") == 1
