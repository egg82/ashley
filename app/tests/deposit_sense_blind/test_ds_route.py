"""`GET /api/reminders` field `on_deposit`: the rule of a reminder that waits on a deposit, in words built from its
fields; None for every other reminder. `DELETE` cancels an armed one like any."""

from collections.abc import Awaitable, Callable
from datetime import timedelta

from ashley.api.person import person_signed_in
from ashley.api.reminder_models import RemindersResponse
from ashley.db.pool import PoolDatabase
from ashley.main import create_app
from ashley.people.model import Person
from ashley.senses.deposit_rule import describe
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.wakes import Reminder
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import run
from ds_support import ARMED_AT, BONUS, BRIEF, CHECKING, NAMES, SAVINGS, Folks, home, rule
from fastapi.testclient import TestClient

PUBLIC = "https://ashley.test"


def client(f: Folks, who: int) -> TestClient:
    app = create_app(Settings(database_url=f.url, build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, Person(who, f.house, "SomeoneZq"))
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


def listing(f: Folks, who: int) -> RemindersResponse:
    with client(f, who) as c:
        got = c.get("/api/reminders")
    assert got.status_code == 200
    return RemindersResponse.model_validate(got.json())


def arranged(db_url: str, scenario: Callable[[Folks], Awaitable[None]]) -> Folks:
    """Run `scenario` against a household, leave the services, and give the household's ids back."""
    box: list[Folks] = []

    async def go() -> None:
        async with home(db_url) as f:
            await scenario(f)
            box.append(f)

    run(go())
    return box[0]


def test_an_armed_reminder_lists_with_its_rule_in_words_and_when_it_was_set(db_url: str) -> None:
    async def scenario(f: Folks) -> None:
        await f.arm(rule(min_cents=150050, payee=BONUS, match="exact"))

    f = arranged(db_url, scenario)
    (one,) = listing(f, f.alana).reminders
    assert one.on_deposit is not None
    assert NAMES[CHECKING] in one.on_deposit and BONUS in one.on_deposit
    assert "1,500.50" in one.on_deposit or "1500.50" in one.on_deposit
    assert one.what == BRIEF and one.state == "scheduled"
    assert one.due_at == ARMED_AT and one.repeat is None


def test_on_deposit_is_the_rule_described_from_its_fields(db_url: str) -> None:
    made = rule(min_cents=150050, payee=BONUS, match="exact")

    async def scenario(f: Folks) -> None:
        await f.arm(made)

    f = arranged(db_url, scenario)
    assert listing(f, f.alana).reminders[0].on_deposit == describe(made)


def test_the_text_follows_the_rules_fields(db_url: str) -> None:
    async def scenario(f: Folks) -> None:
        for made in (rule(CHECKING, 100, "Acme", "exact"), rule(SAVINGS, 100, "Acme", "exact"),
                     rule(CHECKING, 100, "Acme", "contains"), rule(CHECKING, 200, "Acme", "exact")):
            await f.arm(made)

    f = arranged(db_url, scenario)
    texts = [r.on_deposit for r in listing(f, f.alana).reminders]
    assert len(texts) == 4 and None not in texts and len(set(texts)) == 4


def test_a_timed_reminder_and_a_fired_deposit_reminder_have_no_on_deposit(db_url: str) -> None:
    async def scenario(f: Folks) -> None:
        armed_id = await f.arm(rule())
        assert await f.deposits.fire(armed_id, "tx-1")
        await f.wakes.schedule(Reminder(f.house, f.alana, f.alana, "timed", ARMED_AT + timedelta(days=3650), None))

    f = arranged(db_url, scenario)
    got = listing(f, f.alana).reminders
    assert len(got) == 3
    assert [r.what for r in got if r.on_deposit is not None] == [BRIEF]
    assert sorted(r.what for r in got if r.on_deposit is None) == sorted([BRIEF, "timed"])


def test_the_asker_and_the_person_it_is_for_both_see_it(db_url: str) -> None:
    async def scenario(f: Folks) -> None:
        await f.arm(rule(), who=f.sam, made_by=f.alana)

    f = arranged(db_url, scenario)
    assert [r.on_deposit is not None for r in listing(f, f.alana).reminders] == [True]
    assert [r.on_deposit is not None for r in listing(f, f.sam).reminders] == [True]


def test_deleting_an_armed_reminder_cancels_it(db_url: str) -> None:
    ids: list[int] = []

    async def scenario(f: Folks) -> None:
        ids.append(await f.arm(rule()))

    f = arranged(db_url, scenario)
    with client(f, f.alana) as c:
        assert c.delete(f"/api/reminders/{ids[0]}").status_code == 200
        assert c.get("/api/reminders").json()["reminders"] == []
    again: list[int] = []
    run(_armed_count(db_url, again))
    assert again == [0]


async def _armed_count(db_url: str, out: list[int]) -> None:
    db = PoolDatabase(db_url, connect_timeout_s=5.0)
    await db.open()
    try:
        out.append(len(await PostgresDeposits(db).armed()))
    finally:
        await db.close()
