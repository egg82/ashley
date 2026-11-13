"""A model provider's key through the connections routes, the real app and a real database, with the provider's one
read faked: the first household is offered the provider kinds and adds a key, which is checked once, stored sealed and
never on the wire back or in a log line; another household is not offered them, and adding one is 404 with no read
made."""

from collections.abc import Generator

import pytest
from ashley.inference import kinds
from ashley.inference.kinds import ANTHROPIC_API
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient
from test_connections_routes import ORIGIN, as_, client as client, homes as homes, listed, sure as sure
from test_connections_routes import Homes

KEY = "sk-ant-the-households-own-key"
PROVIDERS = ["anthropic", "openai", "gemini", "elevenlabs"]


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> Generator[list[str]]:
    """The URLs the provider kinds' checks read, each answered as the provider would a good key."""
    seen: list[str] = []

    async def answered(http: object, url: str, headers: dict[str, str]) -> None:
        seen.append(url)
    monkeypatch.setattr(kinds, "answered", answered)
    yield seen


def test_the_first_household_adds_a_key_checked_once_and_never_shown(
        client: TestClient, reads: list[str], db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    assert [k.name for k in listed(client).offered][-10:-6] == PROVIDERS
    made = client.post("/api/connections", json={"kind": "anthropic", "label": "", "api_key": KEY}, headers=ORIGIN)
    assert made.status_code == 201, made.text
    assert made.json()["base_url"] == ANTHROPIC_API and reads == [ANTHROPIC_API + "/v1/models"]
    shown = client.get("/api/connections")
    assert KEY not in made.text and KEY not in shown.text and KEY not in caplog.text
    stored = scalar(db_url, "SELECT secret FROM connections WHERE kind = 'anthropic'")
    assert KEY.encode() not in bytes(stored)


def test_another_household_is_not_offered_the_provider_kinds_and_cannot_add_one(
        client: TestClient, homes: Homes, reads: list[str], db_url: str) -> None:
    as_(client, homes.kim_token)
    assert not set(PROVIDERS) & {k.name for k in listed(client).offered}
    made = client.post("/api/connections", json={"kind": "openai", "label": "", "api_key": KEY}, headers=ORIGIN)
    assert made.status_code == 404 and reads == []
    assert scalar(db_url, "SELECT count(*) FROM connections") == 0
