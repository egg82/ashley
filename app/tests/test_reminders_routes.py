"""A person's reminders through the real app and a real database: `GET /api/reminders` lists those for them or made
by them, with their names, local wall time and repeat, soonest first; `DELETE /api/reminders/{id}` cancels one of
those, and any other (another person's, another household's, one already settled) is 404 alike; a write from another
site is refused; and no log line carries what a reminder says."""

import hashlib
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from ashley import logs
from ashley.api.person import SESSION_COOKIE
from ashley.api.reminder_models import Reminder, RemindersResponse
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import scalar
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
ORIGIN = {"origin": PUBLIC}
WHAT = "Change the Bluebird Autosave rule and add another."


@dataclass(frozen=True)
class Homes:
    home: int
    other: int
    alana: int
    sam: int
    kim: int
    alana_token: str
    kim_token: str


def _session(conn: psycopg.Connection, person: int, household: int, sub: str) -> str:
    account = admin.add_account(conn, person, "oidc", sub)
    token = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                 "VALUES (%s, %s, %s, now() + interval '1 day')",
                 (hashlib.sha256(token.encode()).digest(), account, household))
    return token


@pytest.fixture
def homes(db_url: str) -> Homes:
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "other", "UTC")
        alana, sam, kim = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                          admin.add_person(conn, other, "Kim"))
        return Homes(home, other, alana, sam, kim, _session(conn, alana, home, "sub-alana"), _session(conn, kim, other, "sub-k"))


@pytest.fixture
def client(db_url: str, homes: Homes) -> Generator[TestClient]:
    app = create_app(Settings(database_url=db_url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, homes.alana_token, domain="ashley.test")
        yield c


def reminder(url: str, home: int, who: int, by: int, in_days: float, repeat: str | None = None) -> int:
    due = datetime.now(UTC) + timedelta(days=in_days)
    return int(scalar(url, "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, "
                           "brief, repeat) VALUES (%s, 'reminder', %s, 'reminder', %s, %s, %s, %s, %s, %s::jsonb) "
                           "RETURNING id", (home, secrets.token_hex(8), due, due, who, by, WHAT, repeat)))


def test_a_person_sees_reminders_for_them_or_made_by_them_soonest_first(db_url: str, homes: Homes,
                                                                         client: TestClient) -> None:
    monthly = '{"freq": "monthly", "every": 1, "anchor": "2027-03-07T09:00"}'
    later = reminder(db_url, homes.home, homes.alana, homes.alana, 9, monthly)
    for_sam = reminder(db_url, homes.home, homes.sam, homes.alana, 2)
    reminder(db_url, homes.home, homes.sam, homes.sam, 1)
    got = client.get("/api/reminders")
    assert got.status_code == 200
    items = RemindersResponse.model_validate(got.json()).reminders
    assert [i.id for i in items] == [for_sam, later]
    assert (items[0].person.name, items[0].made_by.name, items[0].what) == ("Sam", "Alana", WHAT)
    assert items[0].repeat is None and items[1].repeat == "monthly" and items[1].every == 1
    assert items[1].local_at == items[1].due_at.astimezone(ZoneInfo("America/Denver")).strftime("%Y-%m-%dT%H:%M")


def test_a_person_cancels_one_of_theirs_and_any_other_is_404(db_url: str, homes: Homes, client: TestClient) -> None:
    mine = reminder(db_url, homes.home, homes.alana, homes.alana, 1)
    sams = reminder(db_url, homes.home, homes.sam, homes.sam, 1)
    kims = reminder(db_url, homes.other, homes.kim, homes.kim, 1)
    assert client.delete(f"/api/reminders/{mine}", headers={"origin": "https://elsewhere.test"}).status_code == 403
    assert client.delete(f"/api/reminders/{mine}", headers=ORIGIN).status_code == 200
    for other in (mine, sams, kims, 999999):
        got = client.delete(f"/api/reminders/{other}", headers=ORIGIN)
        assert got.status_code == 404 and got.json()["code"] == "not_found"
    assert client.get("/api/reminders").json()["reminders"] == []
    assert scalar(db_url, "SELECT outcome FROM wakes WHERE id = %s", (mine,)) == "cancelled"


def test_signed_out_is_401_and_no_log_line_carries_what_a_reminder_says(db_url: str, homes: Homes, client: TestClient,
                                                                        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    made = reminder(db_url, homes.home, homes.alana, homes.alana, 1)
    client.get("/api/reminders")
    client.delete(f"/api/reminders/{made}", headers=ORIGIN)
    out = capsys.readouterr().out
    assert "event=reminders.listed" in out and "event=reminders.cancelled" in out
    assert "Bluebird" not in out and "Autosave" not in out
    client.cookies.clear()
    assert client.get("/api/reminders").status_code == 401


def _body(**over: object) -> dict[str, object]:
    when = (datetime.now(ZoneInfo("America/Denver")) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    return {"what": WHAT, "local_at": when, "repeat": "daily", "method": "research", **over}


def test_a_person_sets_a_standing_errand_changes_and_clears_its_method(db_url: str, homes: Homes,
                                                                        client: TestClient) -> None:
    made = client.post("/api/reminders", json=_body(), headers=ORIGIN)
    assert made.status_code == 201
    item = Reminder.model_validate(made.json())
    assert (item.method, item.repeat, item.person.name, item.made_by.name) == ("research", "daily", "Alana", "Alana")
    assert scalar(db_url, "SELECT method FROM wakes WHERE id = %s", (item.id,)) == "research"
    plain = Reminder.model_validate(client.post("/api/reminders", json=_body(method=None), headers=ORIGIN).json())
    assert plain.method is None
    assert [i.method for i in RemindersResponse.model_validate(client.get("/api/reminders").json()).reminders] \
        in (["research", None], [None, "research"])
    cleared = client.patch(f"/api/reminders/{item.id}", json={"method": None}, headers=ORIGIN)
    assert cleared.status_code == 200 and cleared.json()["method"] is None
    assert scalar(db_url, "SELECT method FROM wakes WHERE id = %s", (item.id,)) is None
    set_again = client.patch(f"/api/reminders/{plain.id}", json={"method": "research"}, headers=ORIGIN)
    assert set_again.status_code == 200 and set_again.json()["method"] == "research"
    assert scalar(db_url, "SELECT repeat->>'freq' FROM wakes WHERE id = %s", (plain.id,)) == "daily"


def test_a_method_is_refused_unless_it_is_a_kind_with_a_method_on_a_repeating_reminder(db_url: str, homes: Homes,
                                                                                       client: TestClient) -> None:
    for bad in ({"method": "no-such-kind"}, {"method": "Not A Slug"}, {"repeat": None}):
        got = client.post("/api/reminders", json=_body(**bad), headers=ORIGIN)
        assert got.status_code == 422 and got.json()["code"] == "refused", bad
    assert "research" in client.post("/api/reminders", json=_body(method="nope"), headers=ORIGIN).json()["detail"]
    assert client.post("/api/reminders", json=_body(local_at="2020-01-01T09:00", repeat=None, method=None), headers=ORIGIN).status_code == 422
    assert client.post("/api/reminders", json=_body(extra=1), headers=ORIGIN).status_code == 422
    assert client.post("/api/reminders", json=_body(), headers={"origin": "https://elsewhere.test"}).status_code == 403
    once = reminder(db_url, homes.home, homes.alana, homes.alana, 1)
    for bad in ({"method": "no-such-kind"}, {"method": "research"}):
        got = client.patch(f"/api/reminders/{once}", json=bad, headers=ORIGIN)
        assert got.status_code == 422 and got.json()["code"] == "refused", bad
    assert scalar(db_url, "SELECT method FROM wakes WHERE id = %s", (once,)) is None
    assert client.post("/api/reminders", json=_body(), headers=ORIGIN).status_code == 201
    assert scalar(db_url, "SELECT count(*) FROM wakes WHERE household_id = %s", (homes.home,)) == 2


def test_a_method_changes_only_a_reminder_of_theirs_still_to_fire(db_url: str, homes: Homes, client: TestClient) -> None:
    daily = '{"freq": "daily", "every": 1, "anchor": "2027-03-07T09:00"}'
    sams = reminder(db_url, homes.home, homes.sam, homes.sam, 1, daily)
    kims = reminder(db_url, homes.other, homes.kim, homes.kim, 1, daily)
    for other in (sams, kims, 999999):
        got = client.patch(f"/api/reminders/{other}", json={"method": "research"}, headers=ORIGIN)
        assert got.status_code == 404 and got.json()["code"] == "not_found"
    for id_ in (sams, kims):
        assert scalar(db_url, "SELECT method FROM wakes WHERE id = %s", (id_,)) is None
    by_alana_for_sam = reminder(db_url, homes.home, homes.sam, homes.alana, 1, daily)
    assert client.patch(f"/api/reminders/{by_alana_for_sam}", json={"method": "research"}, headers=ORIGIN).status_code == 200
    assert client.patch(f"/api/reminders/{by_alana_for_sam}", json={}, headers=ORIGIN).status_code == 422
