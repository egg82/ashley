"""Reminders in the wakes store, over a real database: a reminder is due only once its time has come; settling a
repeating one stores exactly one next occurrence however many runners settle it at once; a person lists and cancels
the reminders for them or made by them, never another's or another household's; a settled reminder past its keeping
is pruned while one still to fire never is; and a house wake is due when it arrives, as before."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder, Wake, Wakes
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar

MONTHLY = Repeat("monthly", 1, datetime(2026, 11, 1, 9, 0))
BRIEF = "Move anything over $300 in Bluebird checking to savings."


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[Wakes]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresWakes(db)
    finally:
        await db.close()


def reminder(home: int, who: int, by: int | None = None, *, in_s: float = -1.0,
             repeat: Repeat | None = None, brief: str = BRIEF) -> Reminder:
    return Reminder(home, who, by or who, brief, datetime.now(UTC) + timedelta(seconds=in_s), repeat)


def count(url: str, where: str = "true") -> int:
    return int(scalar(url, f"SELECT count(*) FROM wakes WHERE {where}"))


def test_a_reminder_is_due_only_once_its_time_has_come_and_reads_back_as_scheduled(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as wakes:
            now_id = await wakes.schedule(reminder(home, alana, repeat=MONTHLY))
            later_id = await wakes.schedule(reminder(home, alana, in_s=3600))
            due = await wakes.due(10)
            assert [d.id for d in due] == [now_id]
            got = due[0].wake
            assert isinstance(got, Reminder)
            assert (got.person_id, got.made_by, got.brief, got.repeat) == (alana, alana, BRIEF, MONTHLY)
            assert due[0].age_s >= 0
            assert [s.id for s in await wakes.reminders(home, alana)] == [now_id, later_id]
    run(go())


def test_a_house_wake_is_due_when_it_arrives_beside_reminders_longest_due_first(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    device = int(scalar(db_url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                                "VALUES (%s, 'house', 'house', 'household', 'text', 'chat', decode(%s, 'hex')) "
                                "RETURNING id", (home, f"{home:064x}")))

    async def go() -> None:
        async with store(db_url) as wakes:
            older = await wakes.schedule(reminder(home, alana, in_s=-600))
            house = (await wakes.receive(device, Wake(home, "ctx-1", "alana_arrived", None, None,
                                                      datetime.now(UTC)))).id
            assert [d.id for d in await wakes.due(10)] == [older, house]
            assert isinstance((await wakes.due(10))[1].wake, Wake)
    run(go())


def test_settling_a_repeating_occurrence_stores_one_next_however_many_settle_it(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")
    nxt = datetime(2026, 12, 1, 16, 0, tzinfo=UTC)

    async def go() -> None:
        async with store(db_url) as wakes:
            first = await wakes.schedule(reminder(home, alana, repeat=MONTHLY))
            settled = await asyncio.gather(*(wakes.settle(first, "turn", nxt) for _ in range(4)))
            assert sorted(settled) == [False, False, False, True]
            [following] = [s for s in await wakes.reminders(home, alana) if s.state == "scheduled"]
            assert following.id != first and following.reminder.due_at == nxt
            assert following.reminder.repeat == MONTHLY and following.reminder.brief == BRIEF
            assert await wakes.due(10) == ()
            assert count(db_url) == 2
    run(go())


def test_a_person_lists_and_cancels_reminders_for_them_or_made_by_them_and_no_others(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    alana, sam, kim = person(db_url, home, "Alana"), person(db_url, home, "Sam"), person(db_url, other, "Kim")

    async def go() -> None:
        async with store(db_url) as wakes:
            for_sam_by_alana = await wakes.schedule(reminder(home, sam, alana, in_s=60))
            sams_own = await wakes.schedule(reminder(home, sam, in_s=120))
            kims = await wakes.schedule(reminder(other, kim, in_s=60))
            assert [s.id for s in await wakes.reminders(home, alana)] == [for_sam_by_alana]
            assert [s.id for s in await wakes.reminders(home, sam)] == [for_sam_by_alana, sams_own]
            assert not await wakes.cancel(home, alana, sams_own)
            assert not await wakes.cancel(home, alana, kims)
            assert not await wakes.cancel(other, kim, for_sam_by_alana)
            assert await wakes.cancel(home, alana, for_sam_by_alana)
            assert not await wakes.cancel(home, alana, for_sam_by_alana)
            assert [s.id for s in await wakes.reminders(home, sam)] == [sams_own]
            assert scalar(db_url, "SELECT outcome FROM wakes WHERE id = %s", (for_sam_by_alana,)) == "cancelled"
    run(go())


def test_a_cancelled_repeating_reminder_has_no_next_when_its_firing_settles_after(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as wakes:
            first = await wakes.schedule(reminder(home, alana, repeat=MONTHLY))
            assert await wakes.cancel(home, alana, first)
            assert not await wakes.settle(first, "turn", datetime.now(UTC) + timedelta(days=30))
            assert await wakes.reminders(home, alana) == () and count(db_url) == 1
    run(go())


def test_settled_reminders_past_their_keeping_are_pruned_and_ones_still_to_fire_never(db_url: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as wakes:
            fired = await wakes.schedule(reminder(home, alana))
            cancelled = await wakes.schedule(reminder(home, alana, in_s=60))
            recent = await wakes.schedule(reminder(home, alana))
            waiting = await wakes.schedule(reminder(home, alana, in_s=-30 * 86400))
            assert await wakes.settle(fired, "turn") and await wakes.cancel(home, alana, cancelled)
            assert await wakes.settle(recent, "turn")
            for delivered in (fired, recent):
                await wakes.delivered(delivered, True)
            scalar(db_url, "WITH u AS (UPDATE wakes SET settled_at = now() - interval '8 days' WHERE id = ANY(%s) "
                           "RETURNING 1) SELECT count(*) FROM u", ([fired, cancelled],))
            assert await wakes.prune(7 * 86400) == 2
            left = int(scalar(db_url, "SELECT count(*) FROM wakes WHERE id = ANY(%s)", ([recent, waiting],)))
            assert left == 2 and count(db_url) == 2
    run(go())


@pytest.mark.parametrize("brief", ["", "x" * 501, "a\x00b"], ids=["empty", "long", "nul"])
def test_a_brief_out_of_bounds_is_refused_before_anything_is_written(db_url: str, brief: str) -> None:
    home = household(db_url)
    alana = person(db_url, home, "Alana")

    async def go() -> None:
        async with store(db_url) as wakes:
            with pytest.raises(ValueError):
                await wakes.schedule(reminder(home, alana, brief=brief))
            assert count(db_url) == 0
    run(go())
