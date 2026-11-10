"""`GET /api/spend/routes` and `PUT /api/spend/routes/{task}`: the household's choices as the room shows them, a choice
stored and cleared for the session's own household only, a choice the task does not offer refused with nothing stored,
and `action_judge` shown but never set."""

from collections.abc import Generator

import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.api.spend_routes_models import SpendRouteRefused, SpendRoutesResponse
from ashley.db.database import Database
from ashley.inference import routes
from ashley.inference.household_routes import HouseholdRoutes
from ashley.inference.layered_routes import LayeredRoutes
from ashley.inference.postgres_route_choices import PostgresRouteChoices
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from household_routes_support import data
from spend_support import signed_in

PUBLIC = "https://ashley.test"
WRITE = {"Origin": PUBLIC}


@pytest.fixture
def client(db_url: str) -> Generator[tuple[TestClient, str, int]]:
    token, household = signed_in(db_url)
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        services.register(HouseholdRoutes, LayeredRoutes(data(), {}, lambda: {"alpha", "beta"},
                                                         PostgresRouteChoices(services.get(Database)),
                                                         routes.without_fallback))
        c.cookies.set(SESSION_COOKIE, token, domain="ashley.test")
        yield c, db_url, household


def stored(url: str) -> list[tuple[int, str, str, str]]:
    with psycopg.connect(url) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT household_id, task, provider, model FROM household_routes ORDER BY household_id, task").fetchall()]


def test_the_room_lists_the_household_tasks_then_the_judge(client: tuple[TestClient, str, int]) -> None:
    c, _, _ = client
    got = c.get("/api/spend/routes")
    assert got.status_code == 200
    body = SpendRoutesResponse.model_validate(got.json())
    assert [t.task for t in body.choices] == ["command", "chat", "brainstorm", "action_judge"]
    chat = body.choices[1]
    assert chat.household and chat.chosen is None
    assert [(r.provider, r.model) for r in chat.routes] == [("alpha", "m1"), ("beta", "m1")]
    assert [(r.provider, r.model) for r in chat.options] == [("alpha", "m1"), ("beta", "m1"), ("alpha", "m2")]
    judge = body.choices[-1]
    assert not judge.household and judge.options == [] and judge.chosen is None
    assert body.refresh_s == 30


def test_a_choice_is_stored_for_the_sessions_household_and_cleared(client: tuple[TestClient, str, int]) -> None:
    c, url, household = client
    got = c.put("/api/spend/routes/chat", json={"route": {"provider": "alpha", "model": "m2"}}, headers=WRITE)
    assert got.status_code == 200
    chat = SpendRoutesResponse.model_validate(got.json()).choices[1]
    assert chat.chosen is not None and (chat.chosen.provider, chat.chosen.model) == ("alpha", "m2")
    assert stored(url) == [(household, "chat", "alpha", "m2")]
    cleared = c.put("/api/spend/routes/chat", json={"route": None}, headers=WRITE)
    assert cleared.status_code == 200 and SpendRoutesResponse.model_validate(cleared.json()).choices[1].chosen is None
    assert stored(url) == []


def test_another_households_choice_is_neither_shown_nor_touched(client: tuple[TestClient, str, int]) -> None:
    c, url, _ = client
    with psycopg.connect(url, autocommit=True) as conn:
        other = admin.add_household(conn, "next door", "UTC")
        conn.execute("INSERT INTO household_routes (household_id, task, provider, model) VALUES (%s, 'chat', 'beta', 'm1')",
                     (other,))
    assert SpendRoutesResponse.model_validate(c.get("/api/spend/routes").json()).choices[1].chosen is None
    c.put("/api/spend/routes/chat", json={"route": None}, headers=WRITE)
    assert stored(url) == [(other, "chat", "beta", "m1")]


@pytest.mark.parametrize(("task", "route", "reason"), [
    ("action_judge", {"provider": "alpha", "model": "m1"}, "not_household"),
    ("action_judge", None, "not_household"),
    ("memory_write", {"provider": "alpha", "model": "m1"}, "not_household"),
    ("chat", {"provider": "alpha", "model": "m9"}, "not_offered"),
])
def test_a_choice_the_task_does_not_offer_is_refused_and_nothing_is_stored(
        client: tuple[TestClient, str, int], task: str, route: dict[str, str] | None, reason: str) -> None:
    c, url, _ = client
    got = c.put(f"/api/spend/routes/{task}", json={"route": route}, headers=WRITE)
    assert got.status_code == 422
    assert SpendRouteRefused.model_validate(got.json()).reason == reason
    assert stored(url) == []


def test_an_option_whose_provider_has_no_key_is_refused(client: tuple[TestClient, str, int]) -> None:
    c, url, _ = client
    services.register(HouseholdRoutes, LayeredRoutes(data(), {}, lambda: {"alpha"},
                                                     PostgresRouteChoices(services.get(Database))))
    got = c.put("/api/spend/routes/chat", json={"route": {"provider": "beta", "model": "m1"}}, headers=WRITE)
    assert got.status_code == 422 and got.json()["reason"] == "unwired"
    assert stored(url) == []


def test_an_unknown_task_or_a_body_outside_the_schema_is_validation(client: tuple[TestClient, str, int]) -> None:
    c, _, _ = client
    assert c.put("/api/spend/routes/shout", json={"route": None}, headers=WRITE).status_code == 422
    assert c.put("/api/spend/routes/chat", json={"route": None, "extra": 1}, headers=WRITE).status_code == 422


def test_no_session_is_unauthorized_and_a_cross_site_write_is_forbidden(client: tuple[TestClient, str, int]) -> None:
    c, url, _ = client
    assert c.put("/api/spend/routes/chat", json={"route": {"provider": "beta", "model": "m1"}},
                 headers={"Origin": "https://evil.test"}).status_code == 403
    c.cookies.clear()
    assert c.get("/api/spend/routes").status_code == 401
    assert stored(url) == []
