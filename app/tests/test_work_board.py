"""The board's read model on `/api/work`: a person's pending proposals (one item of kind `proposal`, titled from the
payload by code) and live watches (kind `watch`) beside their errands, each with its lane; the proposals read behind it
(`Proposals.of`); and `DELETE /api/work/watches/{id}`, which ends a person's own live watch and nobody else's."""

import hashlib
import secrets
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.api.work_models import WorkItem, WorkResponse
from ashley.criteria import condition
from ashley.criteria.condition import Condition
from ashley.criteria.items import ItemPredicate
from ashley.db.pool import PoolDatabase
from ashley.main import create_app
from ashley.people import admin
from ashley.senses.proposal_payloads import HeldCall, HeldCalls, HouseChange, Payload, ReminderSchedule, encode
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposals import Proposals
from ashley.senses.wakes import Reminder
from ashley.home_assistant.change import Change
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run, scalar
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

PUBLIC = "https://ashley.test"
WHEN: Condition = ((ItemPredicate("changed", field="seq"),),)
CALL = HeldCall("money_note", {"id": 7}, "note the coffee as groceries")
ELSEWHERE = {"origin": "https://elsewhere.test"}


@dataclass(frozen=True)
class World:
    url: str
    home: int
    alana: int
    sam: int
    other_home: int
    stranger: int
    token: str


@pytest.fixture
def world(db_url: str) -> World:
    with psycopg.connect(db_url) as conn:
        home, other = admin.add_household(conn, "home", "America/Denver"), admin.add_household(conn, "away", "America/Denver")
        alana, sam, stranger = (admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam"),
                                admin.add_person(conn, other, "Pat"))
        account = admin.add_account(conn, alana, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')",
                     (hashlib.sha256(token.encode()).digest(), account, home))
    return World(db_url, home, alana, sam, other, stranger, token)


@pytest.fixture
def client(world: World) -> Generator[TestClient]:
    app = create_app(Settings(database_url=world.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, world.token, domain="ashley.test")
        yield c


def propose(w: World, who: int, payload: Payload, conversation: int = 3, home: int | None = None,
            age: timedelta = timedelta()) -> int:
    topic, stored = encode(payload)
    return int(scalar(w.url, "INSERT INTO proposals (household_id, made_by, conversation_id, turn_id, topic, payload, created_at) "
                             "VALUES (%s, %s, %s, 5, %s, %s, now() - %s) RETURNING id",
                      (w.home if home is None else home, who, conversation, topic, Jsonb(stored), age)))


def reminder(w: World, who: int, brief: str = "Water the ferns") -> ReminderSchedule:
    return ReminderSchedule(Reminder(w.home, who, who, brief, datetime.now(UTC) + timedelta(days=1), None))


def watch(w: World, who: int, home: int | None = None, target: str = "s1", state: str = "armed") -> int:
    return int(scalar(w.url, "INSERT INTO watches (household_id, person_id, kind, target, label, armed_by, track, when_clauses, "
                             "interval_s, expires_at, state, reason, ended_at) VALUES (%s, %s, 'claude_session', %s, 'the build', "
                             "'ashley', ARRAY['seq'], %s, 15, now() + interval '1 hour', %s, "
                             "CASE %s WHEN 'paused' THEN 'unreachable' WHEN 'ended' THEN 'expired' END, "
                             "CASE WHEN %s = 'ended' THEN now() END) RETURNING id",
                      (w.home if home is None else home, who, target, Jsonb(condition.to_json(WHEN)), state, state, state)))


def listed(client: TestClient) -> list[WorkItem]:
    r = client.get("/api/work")
    assert r.status_code == 200
    return WorkResponse.model_validate(r.json()).entries


def test_a_pending_proposal_waits_on_the_person_titled_from_its_payload(world: World, client: TestClient) -> None:
    held = propose(world, world.alana, HeldCalls((CALL, HeldCall("money_note", {"id": 8}, "tag the rent"))))
    ferns = propose(world, world.alana, reminder(world, world.alana), conversation=4)
    house = propose(world, world.alana, HouseChange(Change("delete", "automation", "a1", {}, ()), "remove the automation Porch"))
    by = {i.id: i for i in listed(client) if i.kind == "proposal"}
    assert {i.id: (i.title, i.lane, i.state, i.can_tap, i.conversation_id) for i in by.values()} == {
        held: ("note the coffee as groceries; tag the rent", "waiting", "waiting_on_you", True, 3),
        ferns: ("Water the ferns", "waiting", "waiting_on_you", False, 4),
        house: ("remove the automation Porch", "waiting", "waiting_on_you", False, 3)}


def test_another_persons_another_households_and_a_lapsed_proposal_are_not_listed(world: World, client: TestClient) -> None:
    propose(world, world.sam, HeldCalls((CALL,)))
    propose(world, world.stranger, HeldCalls((CALL,)), home=world.other_home)
    propose(world, world.alana, HeldCalls((CALL,)), home=world.other_home)
    propose(world, world.alana, HeldCalls((CALL,)), age=timedelta(days=30))
    assert listed(client) == []
    mine = propose(world, world.alana, HeldCalls((CALL,)))
    assert [i.id for i in listed(client)] == [mine]


def test_live_watches_are_the_things_she_is_doing_and_ended_or_anothers_are_not(world: World, client: TestClient) -> None:
    armed = watch(world, world.alana)
    paused = watch(world, world.alana, target="s2", state="paused")
    watch(world, world.alana, target="s3", state="ended")
    watch(world, world.sam)
    watch(world, world.stranger, home=world.other_home)
    by = {i.id: i for i in listed(client)}
    assert set(by) == {armed, paused}
    assert (by[armed].kind, by[armed].lane, by[armed].state, by[armed].title) == ("watch", "doing", "running", "the build")
    assert (by[paused].lane, by[paused].state) == ("doing", "stopped")


def test_the_waiting_come_first(world: World, client: TestClient) -> None:
    watch(world, world.alana)
    propose(world, world.alana, HeldCalls((CALL,)))
    assert [i.lane for i in listed(client)] == ["waiting", "doing"]


def test_a_person_ends_their_own_live_watch(world: World, client: TestClient) -> None:
    mine = watch(world, world.alana)
    r = client.delete(f"/api/work/watches/{mine}")
    assert r.status_code == 200 and r.json() == {"id": mine}
    assert scalar(world.url, "SELECT state || ':' || reason FROM watches WHERE id = %s", (mine,)) == "ended:disarmed"
    assert listed(client) == []
    assert client.delete(f"/api/work/watches/{mine}").status_code == 404


def test_nobody_ends_a_watch_that_is_not_theirs_or_is_over(world: World, client: TestClient) -> None:
    sams, strangers = watch(world, world.sam), watch(world, world.stranger, home=world.other_home)
    ended = watch(world, world.alana, target="s9", state="ended")
    for found in (sams, strangers, ended, 99999):
        r = client.delete(f"/api/work/watches/{found}")
        assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert scalar(world.url, "SELECT count(*) FROM watches WHERE state = 'armed'") == 2
    assert client.delete(f"/api/work/watches/{sams}", headers=ELSEWHERE).status_code == 403
    assert client.delete("/api/work/watches/0").status_code == 422
    client.cookies.clear()
    assert client.delete(f"/api/work/watches/{sams}").status_code == 401


def test_a_watch_id_that_is_not_theirs_or_is_over_never_ends_the_live_watch_they_have_on_the_same_target(
        world: World, client: TestClient) -> None:
    mine, sams, over = watch(world, world.alana), watch(world, world.sam), watch(world, world.alana, state="ended")
    assert client.delete(f"/api/work/watches/{sams}").status_code == 404
    assert client.delete(f"/api/work/watches/{over}").status_code == 404
    assert scalar(world.url, "SELECT count(*) FROM watches WHERE state = 'armed'") == 2
    assert client.delete(f"/api/work/watches/{mine}").status_code == 200


def test_the_proposals_read_is_the_persons_own_across_conversations_and_topics_newest_first(world: World) -> None:
    first = propose(world, world.alana, HeldCalls((CALL,)))
    second = propose(world, world.alana, reminder(world, world.alana), conversation=9)
    third = propose(world, world.alana, HouseChange(Change("delete", "automation", "a1", {}, ()), "remove it"), conversation=11)
    propose(world, world.sam, HeldCalls((CALL,)))

    async def go() -> None:
        db = PoolDatabase(world.url, connect_timeout_s=5.0)
        await db.open()
        try:
            found = await PostgresProposals(db).of(world.alana)
            assert [p.id for p in found] == [third, second, first]
            assert [p.conversation_id for p in found] == [11, 9, 3]
            assert isinstance(found[2].payload, HeldCalls) and found[2].payload.calls == (CALL,)
            assert await PostgresProposals(db).of(world.stranger) == ()
        finally:
            await db.close()
    run(go())


def test_the_list_is_all_of_it_or_none_when_proposals_cannot_be_read(world: World, client: TestClient) -> None:
    watch(world, world.alana)
    services.unregister(Proposals)
    assert client.get("/api/work").status_code == 503
