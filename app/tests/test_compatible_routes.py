"""An OpenAI-compatible provider through the connections routes, the real app and a real database, with its one read
faked: an admin of the first household adds one under a route name, picked from the catalogue or at a custom address,
checked once at its own address; a label that is not a route name, or is a shipped provider's, a catalogue provider the
catalogue does not list, or a catalogue provider on a kind priced otherwise, is refused before any read; a person who
is not an admin is offered none and cannot add one; a rename keeps to the same rule."""

from collections.abc import Generator

import pytest
from ashley import services
from ashley.api.connection_models import HouseholdConnection
from ashley.api.models import ErrorResponse
from ashley.inference import compatible
from ashley.inference.catalogue import ModelCatalogue
from catalogue_support import flat, of
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from test_connections_routes import ORIGIN, as_, client as client, homes as homes, listed, sure as sure
from test_connections_routes import Homes

KEY = "gsk-the-deployments-own-key"
GROQ = "https://api.groq.test/openai/v1"


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Generator[list[str]]:
    """The URLs the kind's check reads, each answered as a provider would a good key; and a catalogue listing Groq."""
    seen: list[str] = []

    async def answered(http: object, url: str, headers: dict[str, str]) -> None:
        seen.append(url)
    monkeypatch.setattr(compatible, "answered", answered)
    services.register(ModelCatalogue, of({"groq": {"llama-x": flat()}}))
    yield seen
    services.unregister(ModelCatalogue)


def add(client: TestClient, label: str, provider: str | None = "groq", kind: str = compatible.NAME,
        base: str = GROQ) -> tuple[int, dict[str, object]]:
    body: dict[str, object] = {"kind": kind, "label": label, "base_url": base, "api_key": KEY}
    if provider is not None:
        body["catalogue_provider"] = provider
    got = client.post("/api/connections", json=body, headers=ORIGIN)
    return got.status_code, got.json()


def test_an_admin_adds_one_picked_from_the_catalogue_and_one_at_a_custom_address(
        client: TestClient, reads: list[str], db_url: str) -> None:
    offered = next(k for k in listed(client).offered if k.name == compatible.NAME)
    assert offered.picks_catalogue_provider and offered.label_pattern == compatible.LABEL_PATTERN
    status, body = add(client, "groq")
    assert status == 201, body
    made = HouseholdConnection.model_validate(body)
    assert (made.label, made.base_url, made.catalogue_provider) == ("groq", GROQ, "groq") and KEY not in str(body)
    status, body = add(client, "box", None, base="http://box.test:8000/v1/")
    assert status == 201 and HouseholdConnection.model_validate(body).catalogue_provider is None
    assert reads == [GROQ + "/models", "http://box.test:8000/v1/models"]
    assert scalar(db_url, "SELECT count(*) FROM connections WHERE catalogue_provider = 'groq'") == 1


@pytest.mark.parametrize("label", ["", "Groq", "has space", "openai", "fastembed", "x" * 41])
def test_a_label_that_is_not_a_route_name_or_is_a_shipped_providers_is_bad_label(
        client: TestClient, reads: list[str], db_url: str, label: str) -> None:
    status, body = add(client, label)
    assert status == 422
    if len(label) <= 40:
        assert ErrorResponse.model_validate(body).code == "bad_label"
    assert reads == [] and scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_catalogue_provider_not_listed_or_on_a_kind_priced_otherwise_is_unsupported(
        client: TestClient, reads: list[str], db_url: str) -> None:
    status, body = add(client, "groq", "nobody-lists-this")
    assert status == 422 and ErrorResponse.model_validate(body).code == "unsupported"
    status, body = add(client, "", "groq", kind="sure", base="https://money.test")
    assert status == 422 and ErrorResponse.model_validate(body).code == "unsupported"
    assert reads == [] and scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_person_who_is_not_an_admin_is_offered_none_and_cannot_add_one(
        client: TestClient, homes: Homes, reads: list[str], db_url: str) -> None:
    as_(client, homes.sam_token)
    assert compatible.NAME not in {k.name for k in listed(client).offered}
    status, _ = add(client, "groq")
    assert status == 403 and reads == [] and scalar(db_url, "SELECT count(*) FROM connections") == 0


def test_a_rename_keeps_to_the_route_name_rule(client: TestClient, reads: list[str]) -> None:
    _, body = add(client, "groq")
    made = HouseholdConnection.model_validate(body)
    refused = client.patch(f"/api/connections/{made.id}", json={"label": "Not A Name"}, headers=ORIGIN)
    assert refused.status_code == 422 and ErrorResponse.model_validate(refused.json()).code == "bad_label"
    renamed = client.patch(f"/api/connections/{made.id}", json={"label": "groq-fast"}, headers=ORIGIN)
    assert renamed.status_code == 200 and HouseholdConnection.model_validate(renamed.json()).label == "groq-fast"
