"""The model catalogue's admin routes through the real app: an admin of the first household lists the providers and
one provider's models, upstream's value beside the one in force, and a change stores only what differs from upstream;
anyone else is refused and nothing is stored."""

from collections.abc import Generator

import psycopg
import pytest
from ashley.api.model_catalogue_models import (ModelCatalogueModel, ModelCatalogueModelsResponse, ModelCatalogueRefused,
                                               ModelCatalogueResponse)
from ashley.api.person import SESSION_COOKIE
from ashley.inference.catalogue_model import catalogue_to_json
from ashley.main import create_app
from ashley.settings import Settings
from catalogue_support import captured
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from spend_support import signed_in

PUBLIC = "https://ashley.test"
WRITE = {"Origin": PUBLIC}
HAIKU = {"provider": "anthropic", "model": "claude-haiku-5-5"}


def stored(url: str) -> list[tuple[str, str, str, object, int | None]]:
    with psycopg.connect(url) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT provider, model, field, value, person_id FROM model_catalogue_overrides ORDER BY field").fetchall()]


@pytest.fixture
def client(db_url: str) -> Generator[tuple[TestClient, str, int]]:
    token, household = signed_in(db_url)
    with psycopg.connect(db_url) as conn:
        conn.execute("UPDATE people SET admin = true WHERE household_id = %s", (household,))
        conn.execute("INSERT INTO model_catalogue_fetch (catalogue, fetched_at) VALUES (%s, now())",
                     (Jsonb(catalogue_to_json(captured())),))
        person = conn.execute("SELECT id FROM people WHERE household_id = %s", (household,)).fetchone()
    assert person is not None
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
        yield c, db_url, int(person[0])


def test_an_admin_lists_the_providers_and_the_layers_ages(client: tuple[TestClient, str, int]) -> None:
    c, _, _ = client
    got = c.get("/api/catalogue")
    assert got.status_code == 200
    body = ModelCatalogueResponse.model_validate(got.json())
    assert body.fetched_at is not None and body.snapshot_taken_at is None and body.refresh_s > 0
    anthropic = next(p for p in body.catalogue_providers if p.provider == "anthropic")
    assert (anthropic.name, anthropic.model_count, anthropic.overridden_count) == ("Anthropic", 3, 0)


def test_a_change_stores_only_what_differs_and_shows_upstreams_value_beside_it(
        client: tuple[TestClient, str, int]) -> None:
    c, url, person = client
    got = c.put("/api/catalogue/models", headers=WRITE, json={
        **HAIKU, "set": {"input_usd_per_mtok": 0.2, "output_usd_per_mtok": 0.5}})
    assert got.status_code == 200
    model = ModelCatalogueModel.model_validate(got.json())
    assert model.fields.input_usd_per_mtok == 0.2 and model.fields.tiers == []
    assert model.defaults is not None and model.defaults.input_usd_per_mtok == 0.1 and model.defaults.tiers != []
    assert [o.field_name for o in model.overrides] == ["input_usd_per_mtok"] and model.overrides[0].set_by == person
    assert (model.price.status, model.price.source_layer, model.defaults_layer) == ("priced", "override", "fetch")
    assert stored(url) == [("anthropic", "claude-haiku-5-5", "input_usd_per_mtok", "0.2", person)]
    reset = c.put("/api/catalogue/models", headers=WRITE, json={**HAIKU, "set": {}, "reset": ["input_usd_per_mtok"]})
    assert reset.status_code == 200 and ModelCatalogueModel.model_validate(reset.json()).overrides == []
    assert stored(url) == []


def test_one_provider_lists_its_models_and_an_unknown_one_is_not_found(client: tuple[TestClient, str, int]) -> None:
    c, _, _ = client
    google = ModelCatalogueModelsResponse.model_validate(c.get("/api/catalogue/models",
                                                               params={"provider": "google"}).json())
    zero = next(m for m in google.models if m.model == "lyria-3-clip-preview")
    assert (zero.price.status, zero.fields.tool_call) == ("listed_zero", False)
    assert c.get("/api/catalogue/models", params={"provider": "nobody"}).status_code == 404


def test_a_change_that_sets_and_resets_one_field_or_nothing_is_refused(client: tuple[TestClient, str, int]) -> None:
    c, url, _ = client
    both = c.put("/api/catalogue/models", headers=WRITE,
                 json={**HAIKU, "set": {"free": True}, "reset": ["free"]})
    empty = c.put("/api/catalogue/models", headers=WRITE, json={**HAIKU, "set": {}})
    assert [ModelCatalogueRefused.model_validate(r.json()).reason for r in (both, empty)] == ["set_and_reset", "empty"]
    assert c.put("/api/catalogue/models", headers=WRITE,
                 json={**HAIKU, "set": {"input_usd_per_mtok": -1}}).status_code == 422
    assert stored(url) == []


def test_anyone_but_an_admin_of_the_first_household_is_refused(client: tuple[TestClient, str, int]) -> None:
    c, url, _ = client
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE people SET admin = false")
    assert c.get("/api/catalogue").json()["code"] == "admin_only"
    assert c.put("/api/catalogue/models", headers=WRITE, json={**HAIKU, "set": {"free": True}}).status_code == 403
    assert stored(url) == []
    c.cookies.clear()
    assert c.get("/api/catalogue").status_code == 401
