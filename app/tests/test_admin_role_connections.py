"""Only an admin changes a connection of a `deployment` kind (a model provider's key), through the real connections
routes and database with the provider's read faked; a household's own connections stay any member's (`decisions.md`,
"An admin changes what the deployment shares"). Alana is the first household's admin, Sam is of it and is not."""

from collections.abc import Generator
from dataclasses import replace

import pytest
from ashley.inference import kinds
from ashley.api.admin_gate import may_change
from ashley.inference.kinds import ANTHROPIC, ANTHROPIC_API
from ashley.people.model import Person
from ashley.signin.model import SignedIn
from connection_routes_support import delete_kind, put_kind
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from money_support import BASE, KEY
from test_connections_routes import ORIGIN, as_, client as client, homes as homes, listed, sure as sure
from test_connections_routes import Homes

PROVIDER_KEY = "sk-ant-the-deployments-key"
PROVIDERS = {"anthropic", "openai", "gemini", "elevenlabs"}
ADD = {"kind": "anthropic", "label": "", "api_key": PROVIDER_KEY}


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Generator[list[str]]:
    """The URLs the provider kinds' checks read, each answered as the provider would a good key."""
    seen: list[str] = []

    async def answered(http: object, url: str, headers: dict[str, str]) -> None:
        seen.append(url)
    monkeypatch.setattr(kinds, "answered", answered)
    yield seen


@pytest.fixture
def alana_admin(homes: Homes, db_url: str) -> Homes:
    scalar(db_url, "UPDATE people SET admin = true WHERE id = %s RETURNING id", (homes.alana,))
    return homes


def _admin_only(response: object) -> bool:
    status: int = getattr(response, "status_code")
    return status == 403 and getattr(response, "json")()["code"] == "admin_only"


def _key_row(client: TestClient) -> int:
    made = client.post("/api/connections", json=ADD, headers=ORIGIN)
    assert made.status_code == 201, made.text
    row: int = made.json()["id"]
    return row


def test_a_non_admin_of_the_first_household_is_offered_no_provider_kind_and_adding_one_is_admin_only(
        client: TestClient, alana_admin: Homes, reads: list[str], db_url: str) -> None:
    as_(client, alana_admin.sam_token)
    assert not PROVIDERS & {k.name for k in listed(client).offered}
    assert _admin_only(client.post("/api/connections", json=ADD, headers=ORIGIN))
    assert reads == [] and scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_non_admin_cannot_replace_rename_or_remove_a_providers_key_and_is_told_so(
        client: TestClient, alana_admin: Homes, reads: list[str], db_url: str) -> None:
    row = _key_row(client)
    as_(client, alana_admin.sam_token)
    shown = next(c for c in listed(client).connections if c.id == row)
    assert not shown.can_change
    assert _admin_only(client.put(f"/api/connections/{row}", json={"api_key": "sk-ant-other"}, headers=ORIGIN))
    assert _admin_only(client.patch(f"/api/connections/{row}", json={"label": "mine"}, headers=ORIGIN))
    assert _admin_only(client.delete(f"/api/connections/{row}", headers=ORIGIN))
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE label = ''") == 1


def test_an_admin_adds_replaces_and_removes_a_providers_key(client: TestClient, alana_admin: Homes,
                                                            reads: list[str]) -> None:
    me = client.get("/api/me").json()["person"]
    assert me["admin"] is True
    assert PROVIDERS <= {k.name for k in listed(client).offered}
    row = _key_row(client)
    assert reads == [ANTHROPIC_API + "/v1/models"]
    assert next(c for c in listed(client).connections if c.id == row).can_change
    assert client.put(f"/api/connections/{row}", json={"api_key": "sk-ant-rotated"}, headers=ORIGIN).status_code == 200
    assert client.delete(f"/api/connections/{row}", headers=ORIGIN).status_code == 204


def test_a_households_own_connection_is_still_any_members(client: TestClient, alana_admin: Homes) -> None:
    as_(client, alana_admin.sam_token)
    made = put_kind(client, "sure", json={"base_url": BASE, "api_key": KEY}, headers=ORIGIN)
    assert made.status_code == 200, made.text
    assert made.json()["can_change"] is True
    as_(client, alana_admin.alana_token)
    assert put_kind(client, "sure", json={"base_url": BASE, "api_key": KEY}, headers=ORIGIN).status_code == 200
    as_(client, alana_admin.sam_token)
    assert delete_kind(client, "sure", headers=ORIGIN).status_code == 204


def test_only_an_admin_of_the_first_household_may_change_a_deployment_kind() -> None:
    deployment_kind = ANTHROPIC.kind
    household_kind = replace(ANTHROPIC.kind, deployment=False)

    def who(household: int, is_admin: bool) -> SignedIn:
        return SignedIn(1, Person(1, household, "x", is_admin))
    assert may_change(who(1, True), deployment_kind)
    assert not may_change(who(1, False), deployment_kind)
    assert not may_change(who(2, True), deployment_kind)
    assert may_change(who(2, False), household_kind)
