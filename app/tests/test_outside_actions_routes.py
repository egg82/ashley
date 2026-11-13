"""`GET /api/outside-actions` through the real app and a real database: a person sees what she did for them with no OK,
newest first, with the headline, the plain-words summary and the judge's reason; never another person's rows in the
household or another household's; `limit` bounds the list; signed out is 401; and no log line carries a summary."""

import hashlib
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from ashley import logs
from ashley.api.outside_models import OutsideActionsResponse
from ashley.api.person import SESSION_COOKIE
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
SUMMARY = "Filed the Bluebird statement under Autosave."


@dataclass(frozen=True)
class Homes:
    home: int
    other: int
    alana: int
    sam: int
    kim: int
    alana_token: str


@pytest.fixture
def homes(db_url: str) -> Homes:
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "UTC"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        account = admin.add_account(conn, alana, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
        return Homes(home, other, alana, sam, kim, token)


@pytest.fixture
def client(db_url: str, homes: Homes) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, homes.alana_token, domain="ashley.test")
        yield c


def did(url: str, household: int, person: int, tool: str, minutes_ago: int = 0, tier: str = "runs",
        explanation: str | None = None, label: str = "Filed a transaction", summary: str = SUMMARY) -> None:
    with psycopg.connect(url) as conn:
        conn.execute("INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, tier, "
                     "decision, reason, explanation, at, label) VALUES (%s, %s, 1, 1, %s, %s, %s, 'run', NULL, %s, %s, %s)",
                     (household, person, tool, summary, tier, explanation,
                      datetime.now(UTC) - timedelta(minutes=minutes_ago), label))


def test_a_person_sees_what_ran_for_them_newest_first_with_its_why(db_url: str, homes: Homes, client: TestClient) -> None:
    did(db_url, homes.home, homes.alana, "mail_label", minutes_ago=30, label="Labelled a message")
    did(db_url, homes.home, homes.alana, "money_categorise", minutes_ago=5, tier="judged", explanation="You asked for it.")
    did(db_url, homes.home, homes.alana, "light", minutes_ago=60, label="")
    got = client.get("/api/outside-actions")
    assert got.status_code == 200
    items = OutsideActionsResponse.model_validate(got.json()).outside_actions
    assert [(i.tier, i.label, i.explanation) for i in items] == [
        ("judged", "Filed a transaction", "You asked for it."), ("runs", "Labelled a message", None), ("runs", None, None)]
    assert items[0].summary == SUMMARY and items[0].at > items[1].at > items[2].at


def test_only_their_own_rows_are_listed(db_url: str, homes: Homes, client: TestClient) -> None:
    did(db_url, homes.home, homes.alana, "mail_label", summary="mine")
    did(db_url, homes.home, homes.sam, "mail_label", summary="sams")
    did(db_url, homes.other, homes.kim, "mail_label", summary="kims")
    did(db_url, homes.other, homes.alana, "mail_label", summary="same person id, another household")
    assert [a["summary"] for a in client.get("/api/outside-actions").json()["outside_actions"]] == ["mine"]


def test_limit_bounds_the_list_and_is_validated(db_url: str, homes: Homes, client: TestClient) -> None:
    for minutes in range(5):
        did(db_url, homes.home, homes.alana, "mail_label", minutes_ago=minutes)
    assert len(client.get("/api/outside-actions", params={"limit": 2}).json()["outside_actions"]) == 2
    assert len(client.get("/api/outside-actions").json()["outside_actions"]) == 5
    assert client.get("/api/outside-actions", params={"limit": 0}).status_code == 422
    assert client.get("/api/outside-actions", params={"limit": 201}).status_code == 422


def test_signed_out_is_401_and_no_log_line_carries_a_summary(db_url: str, homes: Homes, client: TestClient,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    did(db_url, homes.home, homes.alana, "mail_label")
    client.get("/api/outside-actions")
    out = capsys.readouterr().out
    assert "event=outside_actions.listed" in out and "count=1" in out
    assert "Bluebird" not in out and "Autosave" not in out
    client.cookies.clear()
    assert client.get("/api/outside-actions").status_code == 401
