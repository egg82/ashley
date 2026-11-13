"""`GET /api/work` through the real app and a real database: a person's open errands (one-shot and open-ended) and
open benches with the state each record's own fields give, those waiting on them first; another person's and a
settled errand's are absent; and no log line carries what an item says."""

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from ashley.api.person import SESSION_COOKIE
from ashley.api.work_items import bench_item
from ashley.api.work_models import WorkResponse
from ashley.errands.bench_job_model import NewJob
from ashley.main import create_app
from ashley.people import admin
from ashley.settings import Settings
from ashley.workshop.model import Bench
from bench_jobs_support import store
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, scalar
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"
ASK = "Find me a quiet keyboard under eighty dollars."
BRIEF = "Watch the flight price to Lisbon."


@dataclass(frozen=True)
class World:
    url: str
    home: int
    alana: int
    sam: int
    token: str
    conversation: int


@pytest.fixture
def world(db_url: str) -> World:
    with psycopg.connect(db_url) as conn:
        home = admin.add_household(conn, "home", "America/Denver")
        alana, sam = admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam")
        account = admin.add_account(conn, alana, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))
    return World(db_url, home, alana, sam, token, conversation)


@pytest.fixture
def client(world: World) -> Generator[TestClient]:
    app = create_app(Settings(database_url=world.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, world.token, domain="ashley.test")
        yield c


def turn(w: World, who: int, text: str = ASK) -> int:
    return int(scalar(w.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                             "VALUES (%s, %s, 'person', %s, %s, 'private') RETURNING id", (w.conversation, w.home, who, text)))


def errand(w: World, who: int, state: str, told: bool = False, source: str = "house") -> int:
    return int(scalar(w.url, "INSERT INTO errands (household_id, asker_id, conversation_id, turn_id, source, state, "
                             "finished_at, told_at, result, reason, visibility) VALUES (%s, %s, %s, %s, %s, %s, "
                             "CASE WHEN %s = 'done' THEN now() END, CASE WHEN %s THEN now() END, "
                             "CASE WHEN %s = 'done' THEN 'ok' END, CASE WHEN %s = 'given_up' THEN 'expired' END, 'private') "
                             "RETURNING id",
                      (w.home, who, w.conversation, turn(w, who), source, state, state, told, state, state)))


def open_errand(w: World, who: int, state_delivery: str | None = None) -> int:
    due = datetime.now(UTC) + timedelta(hours=3)
    return int(scalar(w.url, "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief, "
                             "ends_at, delivery) VALUES (%s, 'reminder', %s, 'reminder', %s, %s, %s, %s, %s, %s, %s) "
                             "RETURNING id", (w.home, secrets.token_hex(8), due, due, who, who, BRIEF, due + timedelta(days=2),
                                              state_delivery)))


def bench(w: World, who: int, title: str = "Gate") -> int:
    return int(scalar(w.url, "INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, %s) RETURNING id",
                      (w.home, who, title)))


def job(w: World, bench_id: int, state: str | None = None) -> None:
    async def go() -> None:
        async with store(w.url) as jobs:
            made = await jobs.start(NewJob(w.home, w.alana, bench_id, w.conversation, turn(w, w.alana), "agent", "t", "b", (), 1))
            if state is not None:
                claimed = await jobs.claim("agent", 60)
                assert claimed is not None and claimed.id == made
                assert await jobs.state(made, claimed.attempts, "blocked")  # type: ignore[arg-type]

    asyncio.run(go())


def got(client: TestClient) -> WorkResponse:
    r = client.get("/api/work")
    assert r.status_code == 200
    return WorkResponse.model_validate(r.json())


def test_each_record_shows_the_state_its_fields_give_waiting_on_you_first(world: World, client: TestClient) -> None:
    running = errand(world, world.alana, "running")
    errand(world, world.alana, "due")
    done = errand(world, world.alana, "done")
    checking = open_errand(world, world.alana)
    idle, going, blocked = bench(world, world.alana, "Idle"), bench(world, world.alana, "Going"), bench(world, world.alana, "Stuck")
    job(world, blocked, "blocked")
    job(world, going)
    items = got(client).entries
    by = {(i.kind, i.id): i for i in items}
    assert by[("errand", running)].state == "running" and by[("errand", running)].title == ASK
    assert by[("errand", done)].state == "done"
    assert by[("open_errand", checking)].state == "running" and by[("open_errand", checking)].until_local is not None
    assert [by[("bench", b)].state for b in (idle, going, blocked)] == ["open", "running", "waiting_on_you"]
    ranks = [i.state for i in items]
    assert ranks[0] == "waiting_on_you" and ranks[-1] == "done"
    assert len(items) == 7


def test_what_is_over_or_not_theirs_is_not_listed(world: World, client: TestClient) -> None:
    errand(world, world.alana, "done", told=True)
    errand(world, world.alana, "given_up")
    errand(world, world.alana, "done", source="outbox")
    errand(world, world.sam, "running")
    bench(world, world.sam, "Sam's")
    scalar(world.url, "INSERT INTO benches (household_id, owner_id, title, closed_at) VALUES (%s, %s, 'Closed', now()) RETURNING id",
           (world.home, world.alana))
    assert got(client).entries == []


def test_an_undelivered_check_waits_on_the_person_and_a_failed_one_has_stopped(world: World, client: TestClient) -> None:
    due = datetime.now(UTC) - timedelta(minutes=5)
    for outcome, delivery in (("turn", "undelivered"), ("failed", None)):
        scalar(world.url, "INSERT INTO wakes (household_id, kind, event_id, event, at, due_at, person_id, made_by, brief, ends_at, "
                          "settled_at, outcome, delivery) VALUES (%s, 'reminder', %s, 'reminder', %s, %s, %s, %s, %s, %s, now(), "
                          "%s, %s) RETURNING id",
               (world.home, secrets.token_hex(8), due, due, world.alana, world.alana, BRIEF, due + timedelta(days=1),
                outcome, delivery))
    assert sorted(i.state for i in got(client).entries) == ["stopped", "waiting_on_you"]


def test_signed_out_is_401_and_no_log_line_carries_what_an_item_says(world: World, client: TestClient,
                                                                       caplog: pytest.LogCaptureFixture) -> None:
    errand(world, world.alana, "running")
    open_errand(world, world.alana)
    with caplog.at_level(logging.INFO):
        assert len(got(client).entries) == 2
    assert "work.listed" in caplog.text and ASK not in caplog.text and BRIEF not in caplog.text
    client.cookies.clear()
    assert client.get("/api/work").status_code == 401


def test_a_bench_with_an_install_awaiting_approval_waits_on_the_person_whatever_else_runs() -> None:
    b = Bench(1, 1, 1, "Gate", datetime(2026, 11, 1, tzinfo=UTC), None)
    assert bench_item(b, ["running"], True).state == "waiting_on_you"
    assert bench_item(b, ["running", "waiting"], False).state == "waiting_on_you"
    assert bench_item(b, ["running"], False).state == "running"
    assert bench_item(b, [], False).state == "open"
    assert bench_item(b, [], False).at == b.opened_at
