"""The chat and bench routes through the real app over a real database: Conversations and the Workshop are the
production ones; only who is signed in, the people and the model are fakes."""

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.api.person import person_signed_in
from ashley.conversations.inflight import InFlight
from ashley.inference.inference import Inference
from ashley.main import create_app
from ashley.people.model import Person
from ashley.people.people import People
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from ashley.workshop.workshop import Workshop
from fastapi import FastAPI
from fastapi.testclient import TestClient
from respond_support import ALANA, SAM, Fakes

PUBLIC = "https://ashley.test"
Json = dict[str, Any]


def seeded(url: str) -> None:
    """The household and people `respond_support` names, at their ids."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO households (id, name) OVERRIDING SYSTEM VALUE VALUES (%s, 'home')",
                     (ALANA.household_id,))
        for who in (ALANA, SAM):
            conn.execute("INSERT INTO people (id, household_id, name) OVERRIDING SYSTEM VALUE VALUES (%s, %s, 'x')",
                         (who.id, who.household_id))


@dataclass
class Site:
    app: FastAPI
    client: TestClient
    wired: Fakes

    def as_(self, who: Person) -> TestClient:
        self.app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, who)
        return self.client

    def bench(self, who: Person, title: str = "desk") -> int:
        response = self.as_(who).post("/api/benches", json={"title": title})
        assert response.status_code == 200, response.text
        return int(response.json()["id"])

    def put_piece(self, who: Person, bench_id: int, title: str = "Paste", body: str = "body") -> int:
        add = {"type": "add", "kind": "document", "title": title, "body": body, "size": "large"}
        response = self.as_(who).post(f"/api/benches/{bench_id}/commands", json=add)
        assert response.status_code == 200, response.text
        return int(response.json()["piece_id"])


@pytest.fixture
def site(db_url: str, wired: Fakes) -> Generator[Site]:
    seeded(db_url)
    app = create_app(Settings(database_url=db_url, build_version="test", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as client:
        services.register(People, wired.people)
        services.register(InFlight, InFlight.null())
        services.register(Inference, wired.inference)
        yield Site(app, client, wired)
    services.unregister(Workshop)
