"""`GET /api/reminders` and `DELETE /api/reminders/{id}` through the real app and a real database: a person sees and
cancels only what is for them or set by them; anything else is 404 alike; nothing a reminder says is logged."""

import asyncio
from collections.abc import Generator
from dataclasses import dataclass
from datetime import timedelta

import psycopg
import pytest
from ashley import logs
from ashley.api.person import person_signed_in
from ashley.api.reminder_models import ReminderCancelled, RemindersResponse
from ashley.main import create_app
from ashley.people.model import Person
from ashley.senses.repeat import Repeat
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template, person, run, scalar
from datetime import datetime
from fastapi.testclient import TestClient
from rb_support import ZONE, now, reminder, wakes

PUBLIC = "https://ashley.test"


@dataclass
class Home:
    url: str
    one: int
    two: int
    alana: int
    sam: int
    kim: int
    other: int
    me: list[int]


@pytest.fixture
def home(db_url: str) -> Home:
    one, two = household(db_url, "one"), household(db_url, "two")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE households SET timezone = 'America/Denver' WHERE id = %s", (one,))
    return Home(db_url, one, two, person(db_url, one, "Alana"), person(db_url, one, "Sam"), person(db_url, one, "Kim"),
                person(db_url, two, "Other"), [])


def client_for(home: Home, who: int, house: int | None = None) -> TestClient:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, Person(who, house or home.one, "PlantedName-zq"))
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


@pytest.fixture
def seeded(home: Home) -> Generator[dict[str, int]]:
    ids: dict[str, int] = {}

    async def go() -> None:
        async with wakes(home.url) as w:
            ids["mine"] = await w.schedule(reminder(home.one, home.alana, due_in_s=7200.0, brief="ALANAS-OWN-zq"))
            ids["for_sam"] = await w.schedule(reminder(home.one, home.sam, home.alana, due_in_s=3600.0, brief="FOR-SAM-zq",
                                                       repeat=Repeat("weekly", 2, datetime(2030, 1, 1, 9, 0))))
            ids["sams"] = await w.schedule(reminder(home.one, home.sam, home.sam, due_in_s=1800.0, brief="SAMS-OWN-zq"))
            ids["kims"] = await w.schedule(reminder(home.one, home.kim, home.kim, due_in_s=900.0, brief="KIMS-OWN-zq"))
            ids["others"] = await w.schedule(reminder(home.two, home.other, home.other, due_in_s=600.0, brief="OTHERS-zq"))

    run(go())
    yield ids


def test_a_person_lists_theirs_and_those_they_made_soonest_first(home: Home, seeded: dict[str, int]) -> None:
    with client_for(home, home.alana) as c:
        got = c.get("/api/reminders")
    assert got.status_code == 200
    body = RemindersResponse.model_validate(got.json())
    assert [r.id for r in body.reminders] == [seeded["for_sam"], seeded["mine"]]
    for_sam, mine = body.reminders
    assert (for_sam.person.id, for_sam.made_by.id, for_sam.what) == (home.sam, home.alana, "FOR-SAM-zq")
    assert (for_sam.repeat, for_sam.every) == ("weekly", 2)
    assert (mine.person.id, mine.repeat, mine.every) == (home.alana, None, None)
    assert mine.due_at.astimezone(ZONE).strftime("%Y-%m-%dT%H:%M") == mine.local_at


def test_nobody_sees_anothers_reminders_or_another_households(home: Home, seeded: dict[str, int]) -> None:
    with client_for(home, home.kim) as c:
        body = RemindersResponse.model_validate(c.get("/api/reminders").json())
    assert [r.id for r in body.reminders] == [seeded["kims"]]
    with client_for(home, home.other, home.two) as c:
        body = RemindersResponse.model_validate(c.get("/api/reminders").json())
    assert [r.id for r in body.reminders] == [seeded["others"]]
    assert "ALANAS-OWN-zq" not in c.get("/api/reminders").text


def test_a_person_with_none_gets_an_empty_list(home: Home) -> None:
    with client_for(home, home.alana) as c:
        got = c.get("/api/reminders")
    assert got.status_code == 200 and RemindersResponse.model_validate(got.json()).reminders == []


def test_delete_cancels_one_that_is_theirs_and_it_never_fires(home: Home, seeded: dict[str, int]) -> None:
    with client_for(home, home.alana) as c:
        got = c.delete(f"/api/reminders/{seeded['mine']}")
        assert got.status_code == 200 and ReminderCancelled.model_validate(got.json()).id == seeded["mine"]
        assert seeded["mine"] not in [r["id"] for r in c.get("/api/reminders").json()["reminders"]]
    assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (seeded["mine"],)) == "cancelled"


def test_delete_cancels_one_they_made_for_another(home: Home, seeded: dict[str, int]) -> None:
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['for_sam']}").status_code == 200
    with client_for(home, home.sam) as c:
        assert [r["id"] for r in c.get("/api/reminders").json()["reminders"]] == [seeded["sams"]]


def test_delete_of_anothers_or_another_households_or_a_missing_one_is_404_alike_and_changes_nothing(
        home: Home, seeded: dict[str, int]) -> None:
    with client_for(home, home.alana) as c:
        answers = [c.delete(f"/api/reminders/{i}") for i in (seeded["kims"], seeded["others"], 999999)]
    assert [a.status_code for a in answers] == [404, 404, 404]
    assert answers[0].json() == answers[1].json() == answers[2].json()
    with client_for(home, home.kim) as c:
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 404
    unsettled = scalar(home.url, "SELECT count(*) FROM wakes WHERE outcome IS NULL")
    assert unsettled == 5


def test_delete_of_one_fired_and_delivered_is_404(home: Home, seeded: dict[str, int]) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            await w.settle(seeded["mine"], "turn")
            await w.delivered(seeded["mine"], True)

    run(go())
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 404


def test_delete_of_a_repeating_reminder_ends_the_series(home: Home, seeded: dict[str, int]) -> None:
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['for_sam']}").status_code == 200

    async def go() -> None:
        async with wakes(home.url) as w:
            assert await w.settle(seeded["for_sam"], "turn", now() + timedelta(days=14)) is False

    run(go())
    assert scalar(home.url, "SELECT count(*) FROM wakes WHERE outcome IS NULL") == 4


def test_without_a_session_both_routes_are_401(home: Home, seeded: dict[str, int]) -> None:
    app = create_app(Settings(database_url=home.url, build_version="t", public_url=PUBLIC))
    with TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC}) as c:
        assert c.get("/api/reminders").status_code == 401
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 401
    assert scalar(home.url, "SELECT count(*) FROM wakes WHERE outcome IS NULL") == 5


def test_nothing_a_reminder_says_reaches_a_log(home: Home, seeded: dict[str, int], capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    with client_for(home, home.alana) as c:
        c.get("/api/reminders")
        c.delete(f"/api/reminders/{seeded['mine']}")
        c.delete(f"/api/reminders/{seeded['kims']}")
    out = capsys.readouterr()
    text = out.out + out.err
    assert "reminders." in text
    for planted in ("ALANAS-OWN-zq", "FOR-SAM-zq", "KIMS-OWN-zq", "Alana", "Sam", "PlantedName-zq"):
        assert planted not in text


FIRED = ("sending", "undelivered", "failed")


def bring_to(home: Home, id_: int, state: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            if state == "failed":
                await w.settle(id_, "failed")
                return
            await w.settle(id_, "turn")
            if state == "undelivered":
                await w.delivered(id_, False)
            if state == "delivered":
                await w.delivered(id_, True)

    run(go())


def listed_states(home: Home, who: int) -> dict[int, str]:
    with client_for(home, who) as c:
        return {r.id: r.state for r in RemindersResponse.model_validate(c.get("/api/reminders").json()).reminders}


def test_the_list_says_where_each_reminder_stands(home: Home, seeded: dict[str, int]) -> None:
    bring_to(home, seeded["mine"], "undelivered")
    bring_to(home, seeded["for_sam"], "sending")
    assert listed_states(home, home.alana) == {seeded["mine"]: "undelivered", seeded["for_sam"]: "sending"}
    bring_to(home, seeded["sams"], "failed")
    assert listed_states(home, home.sam)[seeded["sams"]] == "failed"
    assert listed_states(home, home.kim) == {seeded["kims"]: "scheduled"}


@pytest.mark.parametrize("state", FIRED)
def test_delete_dismisses_a_fired_reminder_that_is_still_listed(home: Home, seeded: dict[str, int], state: str) -> None:
    bring_to(home, seeded["mine"], state)
    with client_for(home, home.alana) as c:
        got = c.delete(f"/api/reminders/{seeded['mine']}")
        assert got.status_code == 200 and ReminderCancelled.model_validate(got.json()).id == seeded["mine"]
        assert seeded["mine"] not in [r["id"] for r in c.get("/api/reminders").json()["reminders"]]
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 404
    assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (seeded["mine"],)) != "cancelled"


@pytest.mark.parametrize("state", FIRED)
def test_the_one_who_made_it_may_dismiss_a_fired_one_for_another(home: Home, seeded: dict[str, int], state: str) -> None:
    bring_to(home, seeded["for_sam"], state)
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['for_sam']}").status_code == 200
    assert seeded["for_sam"] not in listed_states(home, home.sam)


@pytest.mark.parametrize("state", FIRED)
def test_anothers_fired_reminder_is_404_alike_and_stays_listed_for_its_owner(home: Home, seeded: dict[str, int],
                                                                            state: str) -> None:
    bring_to(home, seeded["kims"], state)
    with client_for(home, home.alana) as c:
        answers = [c.delete(f"/api/reminders/{i}") for i in (seeded["kims"], 999999)]
    assert [a.status_code for a in answers] == [404, 404] and answers[0].json() == answers[1].json()
    with client_for(home, home.other, home.two) as c:
        assert c.delete(f"/api/reminders/{seeded['kims']}").status_code == 404
    assert listed_states(home, home.kim) == {seeded["kims"]: state}


def test_delete_of_a_fired_and_delivered_one_is_404_and_it_is_not_listed(home: Home, seeded: dict[str, int]) -> None:
    bring_to(home, seeded["mine"], "delivered")
    assert seeded["mine"] not in listed_states(home, home.alana)
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 404


def test_delete_still_cancels_a_scheduled_one_and_dismissing_one_leaves_the_others(home: Home, seeded: dict[str, int]) -> None:
    bring_to(home, seeded["mine"], "undelivered")
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 200
        assert c.delete(f"/api/reminders/{seeded['for_sam']}").status_code == 200
    assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (seeded["for_sam"],)) == "cancelled"
    assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (seeded["mine"],)) == "turn"
    assert listed_states(home, home.sam) == {seeded["sams"]: "scheduled"}


def test_a_dismissed_reminder_is_pruned_after_its_keeping_and_a_listed_one_is_not(home: Home, seeded: dict[str, int]) -> None:
    bring_to(home, seeded["mine"], "undelivered")
    bring_to(home, seeded["sams"], "undelivered")
    with client_for(home, home.alana) as c:
        assert c.delete(f"/api/reminders/{seeded['mine']}").status_code == 200

    async def go() -> None:
        async with wakes(home.url) as w:
            await asyncio.sleep(0.3)
            assert await w.prune(0.1) == 1

    run(go())
    assert scalar(home.url, "SELECT count(*) FROM wakes WHERE id = %s", (seeded["sams"],)) == 1
    assert scalar(home.url, "SELECT count(*) FROM wakes WHERE id = %s", (seeded["mine"],)) == 0


def test_dismissing_logs_no_words(home: Home, seeded: dict[str, int], capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    bring_to(home, seeded["mine"], "failed")
    with client_for(home, home.alana) as c:
        c.get("/api/reminders")
        c.delete(f"/api/reminders/{seeded['mine']}")
    out = capsys.readouterr()
    assert "reminders." in out.out + out.err and "ALANAS-OWN-zq" not in out.out + out.err
