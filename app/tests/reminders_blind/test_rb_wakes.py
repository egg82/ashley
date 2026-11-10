"""`Wakes` for reminders on a real database: scheduled, due only when due, settled once with one successor however many
settlers race, listed and cancelled only by the household's people it is for or made by, pruned only once settled."""

import asyncio
from datetime import timedelta

import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import MAX_BRIEF, NullWakes, Reminder, WakesUnavailable
from contract.conversations_support import run, scalar
from rb_support import PLANTED, Home, monthly_first, now, reminder, wakes


def test_a_scheduled_reminder_is_due_when_its_time_has_come_and_comes_back_whole(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            r = reminder(home.one, home.alana, home.sam, due_in_s=-30.0, repeat=monthly_first(2))
            id_ = await w.schedule(r)
            (due,) = await w.due(10)
            assert due.id == id_ and due.wake == r
            assert 29.0 < due.age_s < 120.0

    run(go())


def test_a_reminder_not_yet_due_is_not_returned_until_it_is(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, due_in_s=1.0))
            assert await w.due(10) == ()
            await asyncio.sleep(1.4)
            assert [d.id for d in await w.due(10)] == [id_]

    run(go())


def test_due_is_longest_due_first_and_at_most_limit(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            late = await w.schedule(reminder(home.one, home.alana, due_in_s=-10.0))
            old = await w.schedule(reminder(home.one, home.alana, due_in_s=-100.0))
            mid = await w.schedule(reminder(home.one, home.alana, due_in_s=-50.0))
            assert [d.id for d in await w.due(10)] == [old, mid, late]
            assert [d.id for d in await w.due(2)] == [old, mid]

    run(go())


def test_settling_once_wins_and_a_second_settle_changes_nothing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana))
            assert await w.settle(id_, "turn") is True
            assert await w.settle(id_, "failed") is False
            assert await w.due(10) == ()
            assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) == "turn"
            assert await w.settle(id_ + 999, "turn") is False

    run(go())


def test_settling_with_a_next_due_stores_the_next_occurrence_and_the_reminder_stays_listed(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            repeat = monthly_first(2)
            r = reminder(home.one, home.alana, home.sam, repeat=repeat)
            id_ = await w.schedule(r)
            nxt = now() + timedelta(days=20)
            assert await w.settle(id_, "turn", nxt) is True
            assert home.rows() == 2
            fired, listed = await w.reminders(home.one, home.alana)
            assert (fired.id, fired.state) == (id_, "sending")
            assert listed.id != id_ and listed.state == "scheduled"
            assert listed.reminder == Reminder(home.one, home.alana, home.sam, PLANTED, nxt, repeat)
            assert await w.due(10) == ()

    run(go())


def test_a_settle_that_loses_stores_no_successor(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            assert await w.settle(id_, "turn", now() + timedelta(days=20)) is True
            assert await w.settle(id_, "turn", now() + timedelta(days=21)) is False
            assert home.rows() == 2
            assert await w.settle(id_ + 999, "turn", now() + timedelta(days=21)) is False
            assert home.rows() == 2

    run(go())


def test_a_settle_without_a_next_due_stores_no_successor(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            assert await w.settle(id_, "failed") is True
            assert home.rows() == 1
            assert [(s.id, s.state) for s in await w.reminders(home.one, home.alana)] == [(id_, "failed")]

    run(go())


def test_two_settlers_at_once_give_one_winner_and_one_next_row(home: Home) -> None:
    async def go() -> None:
        dbs = [PoolDatabase(home.url, connect_timeout_s=5.0) for _ in range(2)]
        for db in dbs:
            await db.open()
        try:
            first, second = PostgresWakes(dbs[0]), PostgresWakes(dbs[1])
            for round_ in range(15):
                id_ = await first.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
                before = home.rows()
                got = await asyncio.gather(first.settle(id_, "turn", now() + timedelta(days=10 + round_)),
                                           second.settle(id_, "turn", now() + timedelta(days=40 + round_)))
                assert sorted(got) == [False, True]
                assert home.rows() == before + 1
        finally:
            for db in dbs:
                await db.close()

    run(go())


def test_a_person_lists_the_reminders_for_them_and_those_they_made_soonest_first(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            later = await w.schedule(reminder(home.one, home.alana, due_in_s=500.0))
            sooner = await w.schedule(reminder(home.one, home.alana, due_in_s=100.0))
            for_sam = await w.schedule(reminder(home.one, home.sam, home.alana, due_in_s=300.0))
            await w.schedule(reminder(home.one, home.sam, home.sam, due_in_s=50.0))
            await w.schedule(reminder(home.one, home.kim, home.kim, due_in_s=60.0))
            alana = await w.reminders(home.one, home.alana)
            assert [s.id for s in alana] == [sooner, for_sam, later]
            assert {s.reminder.household_id for s in alana} == {home.one}
            assert len(await w.reminders(home.one, home.sam)) == 2
            assert len(await w.reminders(home.one, home.kim)) == 1

    run(go())


def test_another_household_sees_nothing_and_a_fired_reminder_is_not_listed(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana))
            assert await w.reminders(home.two, home.alana) == ()
            assert await w.reminders(home.two, home.other) == ()
            assert await w.reminders(home.one, home.other) == ()
            await w.settle(id_, "turn")
            assert await w.reminders(home.two, home.alana) == ()
            assert [(s.id, s.state) for s in await w.reminders(home.one, home.alana)] == [(id_, "sending")]
            await w.delivered(id_, True)
            assert await w.reminders(home.one, home.alana) == ()

    run(go())


def test_cancel_stops_a_reminder_for_its_person_or_its_maker(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            mine = await w.schedule(reminder(home.one, home.alana))
            sams = await w.schedule(reminder(home.one, home.sam, home.alana))
            assert await w.cancel(home.one, home.alana, mine) is True
            assert await w.cancel(home.one, home.sam, sams) is True
            assert await w.due(10) == ()
            assert await w.reminders(home.one, home.alana) == ()
            assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (mine,)) == "cancelled"
            assert await w.cancel(home.one, home.alana, mine) is False

    run(go())


def test_cancel_by_someone_it_is_not_theirs_or_in_another_household_changes_nothing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana))
            assert await w.cancel(home.one, home.kim, id_) is False
            assert await w.cancel(home.two, home.alana, id_) is False
            assert await w.cancel(home.two, home.other, id_) is False
            assert await w.cancel(home.one, home.alana, id_ + 999) is False
            assert [s.id for s in await w.reminders(home.one, home.alana)] == [id_]
            assert [d.id for d in await w.due(10)] == [id_]
            assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) is None

    run(go())


def test_cancel_of_a_fired_reminder_is_false(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana))
            await w.settle(id_, "turn")
            assert await w.cancel(home.one, home.alana, id_) is False
            assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) == "turn"

    run(go())


def test_cancelling_a_repeating_reminder_leaves_no_future_firing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            assert await w.cancel(home.one, home.alana, id_) is True
            assert await w.settle(id_, "turn", now() + timedelta(days=30)) is False
            assert home.rows() == 1
            assert await w.reminders(home.one, home.alana) == ()
            assert await w.due(10) == ()

    run(go())


def test_cancelling_the_next_occurrence_of_a_series_that_has_fired_ends_it(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            await w.settle(id_, "turn", now() + timedelta(days=30))
            await w.delivered(id_, True)
            (nxt,) = await w.reminders(home.one, home.alana)
            assert await w.cancel(home.one, home.alana, nxt.id) is True
            assert await w.reminders(home.one, home.alana) == ()

    run(go())


@pytest.mark.parametrize("brief", ["", "x" * (MAX_BRIEF + 1), "a\x00b"])
def test_a_brief_outside_the_limits_is_a_value_error_and_writes_nothing(home: Home, brief: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            with pytest.raises(ValueError):
                await w.schedule(reminder(home.one, home.alana, brief=brief))
            assert home.rows() == 0

    run(go())


def test_a_brief_of_exactly_the_limit_and_one_character_are_kept(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            await w.schedule(reminder(home.one, home.alana, brief="x" * MAX_BRIEF))
            await w.schedule(reminder(home.one, home.alana, brief="y"))
            assert sorted(len(d.wake.brief) for d in await w.due(10) if isinstance(d.wake, Reminder)) == [1, MAX_BRIEF]

    run(go())


def test_prune_never_removes_an_unfired_reminder_however_old_or_far(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            old = await w.schedule(reminder(home.one, home.alana, due_in_s=-86400 * 30))
            future = await w.schedule(reminder(home.one, home.alana, due_in_s=86400 * 30))
            repeating = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            await asyncio.sleep(0.3)
            assert await w.prune(0.0) == 0
            assert home.rows() == 3
            assert {d.id for d in await w.due(10)} == {old, repeating}
            assert [s.id for s in await w.reminders(home.one, home.alana)].count(future) == 1

    run(go())


def test_prune_removes_a_settled_reminder_past_the_limit_but_not_the_successor(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            await w.settle(id_, "turn", now() + timedelta(days=30))
            await w.delivered(id_, True)
            await asyncio.sleep(0.4)
            assert await w.prune(3600) == 0
            assert await w.prune(0.2) == 1
            assert home.rows() == 1
            assert len(await w.reminders(home.one, home.alana)) == 1

    run(go())


def test_prune_takes_a_cancelled_reminder_past_the_limit(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana))
            await w.cancel(home.one, home.alana, id_)
            await asyncio.sleep(0.3)
            assert await w.prune(0.1) == 1
            assert home.rows() == 0

    run(go())


def test_nothing_of_a_reminder_reaches_a_log(home: Home, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley import logs

    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, brief=PLANTED, repeat=monthly_first(2)))
            await w.due(10)
            await w.reminders(home.one, home.alana)
            await w.settle(id_, "turn", now() + timedelta(days=30))
            await w.delivered(id_, True)
            (nxt,) = await w.reminders(home.one, home.alana)
            await w.cancel(home.one, home.alana, nxt.id)
            await asyncio.sleep(0.2)
            await w.prune(0.1)

    run(go())
    out = capsys.readouterr()
    assert "PLANTED" not in out.out + out.err and "500 dollars" not in out.out + out.err


def test_an_unwired_process_raises_on_every_reminder_call() -> None:
    null = NullWakes()

    async def go() -> None:
        r = reminder(1, 1)
        for call in (null.schedule(r), null.reminders(1, 1), null.cancel(1, 1, 1)):
            with pytest.raises(WakesUnavailable):
                await call

    run(go())


def test_an_unreachable_database_raises_wakes_unavailable() -> None:
    async def go() -> None:
        db = PoolDatabase("postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.5)
        w = PostgresWakes(db)
        for call in (w.schedule(reminder(1, 1)), w.reminders(1, 1), w.cancel(1, 1, 1)):
            with pytest.raises(WakesUnavailable):
                await call

    run(go())
