"""What she decided not to say on her own is recorded (`OutsideRecord.quieted`, `decisions/senses.md`, Initiative): each
turn Initiative keeps quiet is one entry with its person, a `why` code, the score when it had one and its cause; a turn
that goes out, a remark and a reply to a person leave none. The record keeps `quiet_keep_s` and no other person's or
household's entry reads back. On the board (`GET /api/work`) they are one `kept_quiet` item per person, titled by code,
with the count and the newest entries."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from ashley import services
from ashley.api.person import SESSION_COOKIE
from ashley.api.work_models import WorkItem, WorkResponse
from ashley.channels import unprompted
from ashley.channels.model import Inbound
from ashley.db.pool import PoolDatabase
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative, Scored
from ashley.initiative.moment import Moment
from ashley.initiative.remark import Chance
from ashley.initiative.weights import parse
from ashley.main import create_app
from ashley.people import admin
from ashley.senses.outside_record import Cause, OutsideRecord, QuietEntry, Why
from ashley.senses.postgres_outside_record import PostgresOutsideRecord
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template, person, run, scalar
from fastapi.testclient import TestClient
from initiative_support import FLOOR, weights
from outside_record_support import MemoryRecord

PUBLIC = "https://ashley.test"
DAY = 86400.0
SAYS = Reply(spoken="hi", text="hi", says="reply")
NOTHING = Reply(spoken="", text="", says="none")
MOMENT = Moment("wake:7", hour=12)
SILENT_ODDS = [{"from": FLOOR, "full": 0.0, "short": 0.0, "silent": 1.0}]


def turn(quiet: bool = False, moment: Moment | None = MOMENT, unprompted: bool = True, speaker_id: int | None = 5,
         cause: Cause | None = Cause("wake", 7), remark: Chance | None = None) -> Inbound:
    return Inbound(household_id=1, thread="push:5", text="the washer finished", kind="chat", medium="text",
                   audience="owner", speaker_id=speaker_id, shared=False, place=None, channel="device", later=True,
                   source="wake:7", unprompted=unprompted, author="household", taint=None, moment=moment, quiet=quiet,
                   cause=cause, remark=remark)


@pytest.fixture
def record() -> Generator[MemoryRecord]:
    rec = MemoryRecord()
    services.register(OutsideRecord, rec)
    yield rec
    services.unregister(OutsideRecord)
    services.unregister(Initiative)


def decide(reply: Reply, inbound: Inbound, **w: object) -> bool:
    services.register(Initiative, Scored(parse(weights(**w))))
    return asyncio.run(unprompted.decided(reply, inbound, 9))


def kept(rec: MemoryRecord) -> list[tuple[str, float | None]]:
    return [(e.why, e.score) for e in rec.quiet]


def test_a_quiet_decision_records_who_it_was_for_why_and_what_started_the_turn(record: MemoryRecord) -> None:
    assert decide(SAYS, turn(quiet=True)) is False
    (e,) = record.quiet
    assert (e.household_id, e.person_id, e.conversation_id, e.why, e.score, e.cause) == (1, 5, 9, "quiet_hours", None, Cause("wake", 7))
    assert abs((datetime.now(UTC) - e.at).total_seconds()) < 60


def test_each_reason_initiative_keeps_a_turn_quiet_has_its_own_code(record: MemoryRecord) -> None:
    decide(NOTHING, turn(moment=None))
    assert decide(SAYS, turn(moment=None)) is True, "going out on her says alone is no entry"
    decide(SAYS, turn(), threshold=5.0, odds=[{**SILENT_ODDS[0], "from": 5.0}])
    decide(SAYS, turn(), odds=SILENT_ODDS)
    decide(NOTHING, turn())
    assert kept(record) == [("not_greeting", None), ("below_threshold", 0.0), ("rolled_silent", 0.0), ("said_none", 0.0)]


def test_a_turn_that_goes_out_a_remark_and_a_reply_to_a_person_record_nothing(record: MemoryRecord) -> None:
    assert decide(SAYS, turn()) is True
    chance = Chance("discord:1", hour=12, sent=0, since_typed_s=None, typing_known=True, quiet=False)
    assert decide(NOTHING, turn(remark=chance)) is False, "the remark is kept quiet and is still no entry"
    assert decide(NOTHING, turn(unprompted=False)) is True
    assert record.quiet == []


def test_a_turn_for_no_one_records_with_no_person(record: MemoryRecord) -> None:
    decide(NOTHING, turn(speaker_id=None, cause=None))
    (e,) = record.quiet
    assert e.person_id is None and e.cause is None


def test_a_record_that_cannot_be_written_does_not_stop_the_turn(caplog: pytest.LogCaptureFixture) -> None:
    services.unregister(OutsideRecord)
    try:
        assert decide(NOTHING, turn()) is False
    finally:
        services.unregister(Initiative)
    assert any("initiative.quiet_unrecorded" in r.getMessage() for r in caplog.records)


@asynccontextmanager
async def store(url: str, quiet_keep_s: float = 7 * DAY) -> AsyncGenerator[PostgresOutsideRecord]:
    database = PoolDatabase(url, connect_timeout_s=5.0)
    await database.open()
    try:
        yield PostgresOutsideRecord(database, 90 * DAY, 7 * DAY, quiet_keep_s)
    finally:
        await database.close()


def entry(home: int, who: int | None, days_ago: float = 0.0, why: Why = "rolled_silent",
          cause: Cause | None = None) -> QuietEntry:
    return QuietEntry(home, who, 40, datetime.now(UTC) - timedelta(days=days_ago), why, 1.5, cause)


def test_an_entry_reads_back_with_its_fields_and_the_count_covers_more_than_the_latest(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as rec:
            assert await rec.quiet_of_person(home, alana, 3) is None
            await rec.quieted(entry(home, alana, 4, "quiet_hours"))
            for days in (3, 2, 1):
                await rec.quieted(entry(home, alana, days, why="said_none", cause=Cause("watch", days)))
            got = await rec.quiet_of_person(home, alana, 2)
            assert got is not None and got.count == 4
            assert [(e.why, e.score, e.cause) for e in got.latest] == [("said_none", 1.5, Cause("watch", 1)),
                                                                        ("said_none", 1.5, Cause("watch", 2))]
            assert got.id == int(scalar(db_url, "SELECT max(id) FROM kept_quiet"))

    run(go())


def test_an_entry_past_seven_days_is_pruned_by_the_next_write_and_never_counted(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as rec:
            await rec.quieted(entry(home, alana, 8))
            assert int(scalar(db_url, "SELECT count(*) FROM kept_quiet")) == 1, "nothing prunes until the next write: control"
            assert await rec.quiet_of_person(home, alana, 3) is None, "past the keep it is not counted before it is pruned"
            await rec.quieted(entry(home, alana, 6))
            assert int(scalar(db_url, "SELECT count(*) FROM kept_quiet")) == 1
            got = await rec.quiet_of_person(home, alana, 3)
            assert got is not None and got.count == 1

    run(go())


def test_one_persons_and_one_households_entries_are_never_anothers(db_url: str) -> None:
    home, away = household(db_url), household(db_url)
    alana, sam, pat = person(db_url, home, "Alana"), person(db_url, home, "Sam"), person(db_url, away, "Pat")

    async def go() -> None:
        async with store(db_url) as rec:
            await rec.quieted(entry(home, alana))
            await rec.quieted(entry(home, sam))
            await rec.quieted(entry(home, sam))
            await rec.quieted(entry(home, None))
            await rec.quieted(entry(away, pat))
            await rec.quieted(entry(away, alana))
            for who, home_of, count in ((alana, home, 1), (sam, home, 2), (pat, away, 1)):
                got = await rec.quiet_of_person(home_of, who, 5)
                assert got is not None and got.count == count and {e.household_id for e in got.latest} == {home_of}
            assert await rec.quiet_of_person(home, pat, 5) is None

    run(go())


@dataclass(frozen=True)
class World:
    url: str
    home: int
    alana: int
    sam: int
    token: str


@pytest.fixture
def world(db_url: str) -> World:
    import hashlib
    import secrets
    with psycopg.connect(db_url) as conn:
        home = admin.add_household(conn, "home", "America/Denver")
        alana, sam = admin.add_person(conn, home, "Alana"), admin.add_person(conn, home, "Sam")
        account = admin.add_account(conn, alana, "oidc", "sub-alana")
        token = secrets.token_urlsafe(16)
        conn.execute("INSERT INTO sessions (token_sha256, account_id, household_id, expires_at) "
                     "VALUES (%s, %s, %s, now() + interval '1 day')", (hashlib.sha256(token.encode()).digest(), account, home))
    return World(db_url, home, alana, sam, token)


@pytest.fixture
def client(world: World) -> Generator[TestClient]:
    app = create_app(Settings(database_url=world.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.cookies.set(SESSION_COOKIE, world.token, domain="ashley.test")
        yield c


def put(w: World, who: int, days_ago: float, why: Why, cause: Cause | None = None) -> None:
    async def go() -> None:
        async with store(w.url, 30 * DAY) as rec:
            await rec.quieted(entry(w.home, who, days_ago, why, cause))
    run(go())


def listed(client: TestClient) -> list[WorkItem]:
    got = client.get("/api/work")
    assert got.status_code == 200
    return WorkResponse.model_validate(got.json()).entries


def test_the_board_shows_one_item_with_the_count_and_the_newest_entries(world: World, client: TestClient) -> None:
    assert listed(client) == []
    put(world, world.alana, 5, "quiet_hours")
    whys: list[tuple[int, Why]] = [(3, "below_threshold"), (2, "said_none"), (1, "rolled_silent")]
    for days, why in whys:
        put(world, world.alana, days, why, Cause("wake", days))
    put(world, world.sam, 0.5, "said_none")
    (item,) = listed(client)
    assert (item.kind, item.lane, item.state, item.title) == ("kept_quiet", "kept_quiet", "done", "Kept quiet 4 times")
    assert item.kept_quiet is not None and item.kept_quiet.count == 4
    assert [(e.why, None if e.cause is None else (e.cause.kind, e.cause.id)) for e in item.kept_quiet.latest] == [
        ("rolled_silent", ("wake", 1)), ("said_none", ("wake", 2)), ("below_threshold", ("wake", 3))]
    assert item.at == item.kept_quiet.latest[0].at
    assert item.id == int(scalar(world.url, "SELECT max(id) FROM kept_quiet WHERE person_id = %s", (world.alana,)))


def test_a_single_entry_is_titled_once_and_the_board_hides_a_lapsed_one(world: World, client: TestClient) -> None:
    put(world, world.alana, 8, "said_none")
    assert listed(client) == [], "past the 7-day keep it is not shown though nothing has pruned it"
    put(world, world.alana, 0, "said_none")
    (item,) = listed(client)
    assert item.title == "Kept quiet once" and item.kept_quiet is not None and item.kept_quiet.count == 1
