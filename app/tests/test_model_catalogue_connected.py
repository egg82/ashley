"""The catalogue's providers say whether the deployment holds a connection priced as them: none to begin with, a Gemini
key makes Google connected, an OpenAI-compatible provider is the one it names, and connections that cannot be read are
unknown, not "not connected"."""

import psycopg
import pytest
from ashley import services
from ashley.api.model_catalogue_models import ModelCatalogueResponse
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.inference import compatible, kinds
from ashley.inference.catalogue_model import catalogue_to_json
from catalogue_support import captured
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from test_connections_routes import ORIGIN, client as client, homes as homes, sure as sure


@pytest.fixture(autouse=True)
def reads(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def answered(http: object, url: str, headers: dict[str, str]) -> None:
        return None
    monkeypatch.setattr(kinds, "answered", answered)
    monkeypatch.setattr(compatible, "answered", answered)
    with psycopg.connect(db_url) as conn:
        conn.execute("INSERT INTO model_catalogue_fetch (catalogue, fetched_at) VALUES (%s, now())",
                     (Jsonb(catalogue_to_json(captured())),))


def connected(client: TestClient) -> dict[str, bool | None]:
    got = client.get("/api/catalogue")
    assert got.status_code == 200, got.text
    body = ModelCatalogueResponse.model_validate(got.json())
    assert {p.provider for p in body.catalogue_providers} >= {"anthropic", "google", "openai"}
    return {p.provider: p.has_connection for p in body.catalogue_providers}


def test_a_provider_is_connected_once_a_connection_is_priced_as_it(client: TestClient) -> None:
    assert set(connected(client).values()) == {False}
    made = client.post("/api/connections", json={"kind": "gemini", "label": "", "api_key": "k"}, headers=ORIGIN)
    assert made.status_code == 201, made.text
    now = connected(client)
    assert now["google"] is True and now["anthropic"] is False and now["openai"] is False


def test_an_openai_compatible_provider_is_the_catalogue_provider_it_names(client: TestClient) -> None:
    assert set(connected(client).values()) == {False}
    made = client.post("/api/connections", headers=ORIGIN, json={
        "kind": "openai_compatible", "label": "mine", "api_key": "k", "base_url": "https://api.openai.com/v1",
        "catalogue_provider": "openai"})
    assert made.status_code == 201, made.text
    now = connected(client)
    assert now["openai"] is True and now["google"] is False


def test_connections_that_cannot_be_read_are_unknown(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(self: Connections, household_id: int, person_id: int | None = None) -> None:
        raise ConnectionsUnavailable("down")
    monkeypatch.setattr(type(services.get(Connections)), "of_household", down)
    assert set(connected(client).values()) == {None}
