"""What a person writes about a herdr machine on its connection: stored with the connection by `PATCH
/api/connections/{id}`, alone or with a new label, cleared by an empty one, listed with the connection, refused for a kind
with nothing to describe, and kept when the connection is later renamed."""

from collections.abc import Generator
from dataclasses import dataclass

import pytest
from ashley import services
from ashley.api.connection_models import HouseholdConnection
from ashley.herdr.bridge import Bridge, NullBridge
from ashley.connections.connections import Connections
from ashley.herdr.model import Access, Whoami
from ashley.main import create_app
from ashley.settings import Settings
from ashley.sure.client import Sure
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from money_support import BASE, KEY, FakeSure
from test_connections_routes import APP_KEY, ORIGIN, PUBLIC, Homes, as_, homes as homes, listed, sure as sure

ADDRESS = f"https://bench.test:7843#sha256={'0' * 64}"
ABOUT = "The personal workstation, in the office near the workbench"


@dataclass
class Answering(NullBridge):
    async def whoami(self, access: Access) -> Whoami:
        return Whoami("0.5.0", "0.9.5", str(access.person))


@pytest.fixture
def client(db_url: str, homes: Homes) -> Generator[TestClient]:
    """The app with herdr offered (its client certificate named) and a bridge that answers `whoami`."""
    services.unregister(Connections)
    settings = Settings(database_url=db_url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY,
                        herdr_client_cert_file="/none/cert.pem", herdr_client_key_file="/none/key.pem")
    app = create_app(settings)
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(Bridge, Answering())
        as_(c, homes.alana_token)
        yield c
    services.unregister(Bridge)
    services.unregister(Connections)


def machine(client: TestClient, label: str = "workstation") -> HouseholdConnection:
    got = client.post("/api/connections", json={"kind": "herdr", "label": label, "base_url": ADDRESS, "token": "tok"},
                      headers=ORIGIN)
    assert got.status_code == 201, got.text
    return HouseholdConnection.model_validate(got.json())


def patch(client: TestClient, connection: int, body: dict[str, object]) -> tuple[int, dict[str, object]]:
    got = client.patch(f"/api/connections/{connection}", json=body, headers=ORIGIN)
    return got.status_code, got.json()


def test_a_new_machine_has_no_description_and_its_kind_takes_one(client: TestClient) -> None:
    made = machine(client)
    assert made.description == ""
    kinds = {k.name: k.takes_description for k in listed(client).offered}
    assert kinds["herdr"] and not kinds["sure"]


def test_a_description_is_stored_listed_trimmed_and_cleared(client: TestClient) -> None:
    made = machine(client)
    status, body = patch(client, made.id, {"description": f"  {ABOUT}  "})
    assert status == 200 and body["description"] == ABOUT and body["label"] == "workstation"
    assert [c.description for c in listed(client).connections] == [ABOUT]
    status, body = patch(client, made.id, {"description": ""})
    assert status == 200 and body["description"] == ""


def test_a_label_and_a_description_change_together_and_a_rename_keeps_the_description(client: TestClient) -> None:
    made = machine(client)
    status, body = patch(client, made.id, {"label": "bench", "description": ABOUT})
    assert status == 200 and (body["label"], body["description"]) == ("bench", ABOUT)
    status, body = patch(client, made.id, {"label": "desk"})
    assert status == 200 and (body["label"], body["description"]) == ("desk", ABOUT)


def test_a_description_is_bounded_and_a_holder_is_sent_alone(client: TestClient) -> None:
    made = machine(client)
    assert patch(client, made.id, {"description": "x" * 281})[0] == 422
    assert patch(client, made.id, {"description": "x" * 280})[0] == 200
    assert patch(client, made.id, {"description": "a", "holder": "household"})[0] == 422
    assert patch(client, made.id, {})[0] == 422


def test_a_kind_with_nothing_to_describe_refuses_one(client: TestClient, sure: FakeSure) -> None:
    services.register(Sure, sure.client())
    got = client.post("/api/connections", json={"kind": "sure", "label": "", "base_url": BASE, "api_key": KEY},
                      headers=ORIGIN)
    assert got.status_code == 201, got.text
    made = HouseholdConnection.model_validate(got.json())
    status, body = patch(client, made.id, {"description": "x"})
    assert status == 422 and body["code"] == "unsupported"
    assert listed(client).connections[0].description == ""
    services.unregister(Sure)
