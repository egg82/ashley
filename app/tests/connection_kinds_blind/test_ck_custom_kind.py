"""The registry is the one list of kinds: a kind registered in `ConnectionKinds` is offered, connected, listed and
removed by the same routes as the four built in, with nothing else edited; one that is not registered is 404; a stored
row whose kind is gone cannot be read."""

from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.api.connection_models import ConnectionRefused, ConnectionsResponse, HouseholdConnection
from ashley.api.models import ErrorResponse
from ashley.connections.kinds import ConnectionKind, ConnectionKinds, Refusal
from ashley.wiring import CONNECTION_KINDS
from connection_kinds_blind_support import ORIGIN, People, as_, rows
from fastapi.testclient import TestClient
from connection_routes_support import delete_kind, put_kind

REASONS: tuple[Refusal, ...] = ("bad_url", "key_refused", "unreachable", "wrong_service")


@dataclass
class Checks:
    """The `check` a test kind is declared with: records what it was given, answers with what it is set to."""

    given: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    answer: Refusal | None = None

    async def __call__(self, base_url: str, secret: str, person_id: int) -> Refusal | None:
        self.given.append((base_url, secret))
        return self.answer


def kind(name: str, check: Checks, personal: bool = False, fixed: str | None = None) -> ConnectionKind:
    return ConnectionKind(name=name, title=name.title(), what="music", blurb="blurb", connected="Now connected.",
                          removed="Now removed.", holders=frozenset({"person"} if personal else {"household"}), schemes=frozenset({"https"}),
                          address_placeholder="https://music.example", secret_field="token", secret_label="Token",
                          secret_noun="token", check=check, refusals={r: f"{name} says {r}" for r in REASONS},
                          ports=frozenset(), fixed_address=fixed)


@pytest.fixture
def checks() -> Checks:
    return Checks()


def register(*extra: ConnectionKind) -> None:
    services.register(ConnectionKinds, ConnectionKinds((*CONNECTION_KINDS, *extra)))


def listing(client: TestClient) -> ConnectionsResponse:
    return ConnectionsResponse.model_validate(client.get("/api/connections").json())


def test_a_registered_kind_is_offered_after_the_built_in_ones(client: TestClient, checks: Checks) -> None:
    register(kind("jukebox", checks))
    offered = [o.name for o in listing(client).offered]
    assert offered == [k.name for k in CONNECTION_KINDS] + ["jukebox"]
    info = listing(client).offered[-1]
    assert (info.title, info.what, info.blurb, info.takes_address, info.secret_field) == (
        "Jukebox", "music", "blurb", True, "token")


def test_a_registered_kind_connects_lists_and_disconnects_by_the_one_route(client: TestClient, people: People,
                                                                           checks: Checks, db_url: str) -> None:
    register(kind("jukebox", checks))
    got = put_kind(client, "jukebox", json={"base_url": "https://music.example", "token": "tok-123"},
                     headers=ORIGIN)
    assert got.status_code == 200
    made = HouseholdConnection.model_validate(got.json())
    assert (made.kind, made.base_url, made.personal) == ("jukebox", "https://music.example", False)
    assert checks.given == [("https://music.example", "tok-123")]
    assert [c.kind for c in listing(client).connections] == ["jukebox"]
    as_(client, people, "sam")
    assert [c.kind for c in listing(client).connections] == ["jukebox"]
    assert delete_kind(client, "jukebox", headers=ORIGIN).status_code == 204
    assert rows(db_url) == 0


def test_a_registered_kind_refuses_in_its_own_words(client: TestClient, checks: Checks, db_url: str) -> None:
    register(kind("jukebox", checks))
    checks.answer = "wrong_service"
    got = put_kind(client, "jukebox", json={"base_url": "https://music.example", "token": "tok"},
                     headers=ORIGIN)
    assert got.status_code == 400
    refused = ConnectionRefused.model_validate(got.json())
    assert (refused.reason, refused.detail) == ("wrong_service", "jukebox says wrong_service")
    assert rows(db_url) == 0


def test_a_registered_kind_with_one_address_is_checked_there(client: TestClient, checks: Checks) -> None:
    register(kind("jukebox", checks, fixed="https://api.music.example"))
    assert not listing(client).offered[-1].takes_address
    got = put_kind(client, "jukebox", json={"token": "tok"}, headers=ORIGIN)
    assert got.status_code == 200 and checks.given == [("https://api.music.example", "tok")]


def test_a_registered_personal_kind_is_the_signed_in_persons_own(client: TestClient, people: People,
                                                                 checks: Checks) -> None:
    register(kind("jukebox", checks, personal=True))
    got = put_kind(client, "jukebox", json={"base_url": "https://music.example", "token": "tok"},
                     headers=ORIGIN)
    assert HouseholdConnection.model_validate(got.json()).personal is True
    as_(client, people, "sam")
    assert listing(client).connections == []
    assert delete_kind(client, "jukebox", headers=ORIGIN).status_code == 404


def test_a_kind_that_is_not_registered_is_not_found_and_checked_nowhere(client: TestClient, checks: Checks) -> None:
    got = put_kind(client, "jukebox", json={"base_url": "https://music.example", "token": "tok"},
                     headers=ORIGIN)
    assert got.status_code == 404 and ErrorResponse.model_validate(got.json()).code == "not_found"
    assert checks.given == []


def test_a_stored_row_whose_kind_is_no_longer_registered_cannot_be_read(client: TestClient, checks: Checks) -> None:
    register(kind("jukebox", checks))
    assert put_kind(client, "jukebox", json={"base_url": "https://music.example", "token": "tok"},
                      headers=ORIGIN).status_code == 200
    register()
    got = client.get("/api/connections")
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"


def test_with_no_kinds_registered_nothing_is_offered_or_connected(client: TestClient) -> None:
    services.register(ConnectionKinds, ConnectionKinds.null())
    assert listing(client).offered == []
    assert put_kind(client, "sure", json={"base_url": "https://money.test", "api_key": "k"},
                      headers=ORIGIN).status_code == 404
