"""`Wakes` delivery and dismissal on a real database: a fired reminder (`settle` `turn`) is `sending` until a push try is
recorded (`delivered`), then `undelivered` or off the list; `undelivered` hands out what is due a try; `refire` counts a
firing that could not run; `dismiss` takes a fired reminder off the list; `prune` never removes one that is listed."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import NullWakes, Wake, Wakes, WakesUnavailable
from contract.conversations_support import run, scalar
from rb_support import PLANTED, Home, monthly_first, now, reminder, wakes

LISTED = ("sending", "undelivered", "failed")


async def fire(w: Wakes, home: Home, state: str, who: int | None = None, by: int | None = None) -> int:
    """A reminder of Alana's (or `who`'s, made by `by`) brought to `state`, as the runner and the push singleton would."""
    id_ = await w.schedule(reminder(home.one, home.alana if who is None else who, by))
    if state == "scheduled":
        return id_
    if state == "failed":
        assert await w.settle(id_, "failed") is True
        return id_
    assert await w.settle(id_, "turn") is True
    if state == "undelivered":
        await w.delivered(id_, False)
    if state == "delivered":
        await w.delivered(id_, True)
    return id_


def states(listed: tuple[object, ...]) -> list[tuple[int, str]]:
    return [(getattr(s, "id"), getattr(s, "state")) for s in listed]


def test_a_reminder_walks_scheduled_sending_undelivered_then_off_the_list_when_delivered(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana))
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "scheduled")]
            await w.settle(id_, "turn")
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "sending")]
            await w.delivered(id_, False)
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "undelivered")]
            await w.delivered(id_, False)
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "undelivered")]
            await w.delivered(id_, True)
            assert await w.reminders(home.one, home.alana) == ()

    run(go())


def test_a_reminder_that_could_not_fire_is_listed_failed(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "failed")
            (listed,) = await w.reminders(home.one, home.alana)
            assert (listed.id, listed.state, listed.reminder.brief) == (id_, "failed", PLANTED)

    run(go())


def test_a_cancelled_reminder_is_not_listed_and_a_fired_one_cannot_be_cancelled(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            cancelled = await fire(w, home, "scheduled")
            assert await w.cancel(home.one, home.alana, cancelled) is True
            for state in LISTED:
                id_ = await fire(w, home, state)
                assert await w.cancel(home.one, home.alana, id_) is False
            assert [s.state for s in await w.reminders(home.one, home.alana)] == list(LISTED)

    run(go())


def test_undelivered_hands_out_a_fired_reminder_never_tried_whatever_the_retry_delay(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "sending", who=home.sam, by=home.alana)
            (d,) = await w.undelivered(10, 300.0, 86400.0)
            assert (d.id, d.household_id, d.person_id, d.attempts) == (id_, home.one, home.sam, 0)

    run(go())


def test_a_try_is_counted_and_timed_so_the_reminder_waits_out_the_retry_delay(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "sending")
            await w.delivered(id_, False)
            assert await w.undelivered(10, 300.0, 86400.0) == ()
            (d,) = await w.undelivered(10, 0.0, 86400.0)
            assert (d.id, d.attempts) == (id_, 1)
            await w.delivered(id_, False)
            await w.delivered(id_, False)
            (d,) = await w.undelivered(10, 0.0, 86400.0)
            assert d.attempts == 3
            await asyncio.sleep(0.4)
            assert [x.id for x in await w.undelivered(10, 0.2, 86400.0)] == [id_]
            assert await w.undelivered(10, 600.0, 86400.0) == ()

    run(go())


def test_a_reminder_fired_longer_ago_than_the_window_is_not_handed_out_but_stays_listed(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "undelivered")
            await asyncio.sleep(0.4)
            assert await w.undelivered(10, 0.0, 0.2) == ()
            assert [x.id for x in await w.undelivered(10, 0.0, 3600.0)] == [id_]
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "undelivered")]

    run(go())


def test_a_delivered_reminder_is_never_handed_out_again(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            await fire(w, home, "delivered")
            assert await w.undelivered(10, 0.0, 86400.0) == ()

    run(go())


def test_only_a_reminder_fired_with_a_turn_is_handed_out(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            await fire(w, home, "scheduled")
            cancelled = await fire(w, home, "scheduled")
            await w.cancel(home.one, home.alana, cancelled)
            await fire(w, home, "failed")
            no_person = await w.schedule(reminder(home.one, home.alana))
            await w.settle(no_person, "no_person")
            device = scalar(home.url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256) "
                                      "VALUES (%s, 'hall', 'hall', 'present', 'spoken', 'command', sha256('t'::bytea)) RETURNING id",
                            (home.one,))
            house = await w.receive(device, Wake(home.one, "ev-1", "doorbell", None, None, datetime.now(UTC)))
            await w.settle(house.id, "turn")
            assert await w.undelivered(10, 0.0, 86400.0) == ()

    run(go())


def test_undelivered_is_longest_fired_first_and_at_most_limit(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            first = await fire(w, home, "sending")
            await asyncio.sleep(0.05)
            second = await fire(w, home, "sending", who=home.sam)
            await asyncio.sleep(0.05)
            third = await fire(w, home, "sending")
            assert [d.id for d in await w.undelivered(10, 300.0, 86400.0)] == [first, second, third]
            assert [d.id for d in await w.undelivered(2, 300.0, 86400.0)] == [first, second]

    run(go())


def test_a_delivered_try_on_an_unknown_wake_changes_nothing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "sending")
            await w.delivered(id_ + 999, True)
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "sending")]

    run(go())


def test_refire_counts_firings_and_makes_the_wake_due_again_only_after_the_delay(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "scheduled")
            other = await fire(w, home, "scheduled")
            assert {d.id for d in await w.due(10)} == {id_, other}
            assert await w.refire(id_, 300.0) == 1
            assert [d.id for d in await w.due(10)] == [other]
            assert await w.refire(id_, 0.0) == 2
            assert {d.id for d in await w.due(10)} == {id_, other}
            assert await w.refire(id_, 300.0) == 3
            assert await w.refire(other, 300.0) == 1
            assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (id_,)) is None
            assert {i for i, _ in states(await w.reminders(home.one, home.alana))} == {id_, other}

    run(go())


def test_refire_of_a_settled_cancelled_or_missing_wake_is_zero_and_changes_nothing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            settled = await fire(w, home, "sending")
            cancelled = await fire(w, home, "scheduled")
            await w.cancel(home.one, home.alana, cancelled)
            for id_ in (settled, cancelled, 999999):
                assert await w.refire(id_, 0.0) == 0
            assert await w.due(10) == ()
            assert scalar(home.url, "SELECT outcome FROM wakes WHERE id = %s", (settled,)) == "turn"

    run(go())


def test_a_refired_wake_not_yet_due_again_is_still_listed_scheduled(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, "scheduled")
            await w.refire(id_, 300.0)
            assert states(await w.reminders(home.one, home.alana)) == [(id_, "scheduled")]
            assert await w.cancel(home.one, home.alana, id_) is True

    run(go())


@pytest.mark.parametrize("state", LISTED)
def test_dismiss_takes_a_listed_fired_reminder_off_the_list_once(home: Home, state: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, state)
            assert await w.dismiss(home.one, home.alana, id_) is True
            assert await w.reminders(home.one, home.alana) == ()
            assert await w.dismiss(home.one, home.alana, id_) is False

    run(go())


@pytest.mark.parametrize("state", LISTED)
def test_dismiss_by_the_person_it_is_for_or_the_one_who_made_it_and_no_one_else(home: Home, state: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            mine = await fire(w, home, state, who=home.sam, by=home.alana)
            assert await w.dismiss(home.one, home.kim, mine) is False
            assert await w.dismiss(home.two, home.alana, mine) is False
            assert await w.dismiss(home.two, home.other, mine) is False
            assert await w.dismiss(home.one, home.alana, mine + 999) is False
            assert [s.id for s in await w.reminders(home.one, home.sam)] == [mine]
            assert await w.dismiss(home.one, home.alana, mine) is True
            theirs = await fire(w, home, state, who=home.sam, by=home.alana)
            assert await w.dismiss(home.one, home.sam, theirs) is True

    run(go())


def test_dismiss_refuses_what_is_not_listed_and_fired(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            scheduled = await fire(w, home, "scheduled")
            delivered = await fire(w, home, "delivered")
            cancelled = await fire(w, home, "scheduled")
            await w.cancel(home.one, home.alana, cancelled)
            for id_ in (scheduled, delivered, cancelled):
                assert await w.dismiss(home.one, home.alana, id_) is False
            assert [s.id for s in await w.reminders(home.one, home.alana)] == [scheduled]
            assert [d.id for d in await w.due(10)] == [scheduled]

    run(go())


def test_dismissing_a_fired_occurrence_leaves_the_rest_of_its_series(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await w.schedule(reminder(home.one, home.alana, repeat=monthly_first(2)))
            await w.settle(id_, "turn", now() + timedelta(days=30))
            await w.delivered(id_, False)
            assert await w.dismiss(home.one, home.alana, id_) is True
            (nxt,) = await w.reminders(home.one, home.alana)
            assert nxt.id != id_ and nxt.state == "scheduled" and nxt.reminder.repeat == monthly_first(2)

    run(go())


@pytest.mark.parametrize("state", LISTED)
def test_prune_never_removes_a_listed_reminder_until_it_is_dismissed(home: Home, state: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, state)
            await asyncio.sleep(0.3)
            assert await w.prune(0.1) == 0
            assert home.rows() == 1
            assert states(await w.reminders(home.one, home.alana)) == [(id_, state)]
            await w.dismiss(home.one, home.alana, id_)
            assert await w.prune(3600.0) == 0
            assert await w.prune(0.1) == 1
            assert home.rows() == 0

    run(go())


def test_prune_takes_a_delivered_reminder_past_the_limit_and_leaves_a_listed_one_beside_it(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            done = await fire(w, home, "delivered")
            kept = await fire(w, home, "undelivered")
            await asyncio.sleep(0.3)
            assert await w.prune(0.1) == 1
            assert scalar(home.url, "SELECT count(*) FROM wakes WHERE id = %s", (done,)) == 0
            assert [s.id for s in await w.reminders(home.one, home.alana)] == [kept]

    run(go())


def test_an_unwired_process_raises_on_every_delivery_call() -> None:
    null = NullWakes()

    async def go() -> None:
        for call in (null.refire(1, 1.0), null.undelivered(1, 1.0, 1.0), null.claim(1, 1.0), null.delivered(1, True),
                     null.dismiss(1, 1, 1)):
            with pytest.raises(WakesUnavailable):
                await call

    run(go())


def test_an_unreachable_database_raises_wakes_unavailable_on_every_delivery_call() -> None:
    async def go() -> None:
        db = PoolDatabase("postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.1)
        w = PostgresWakes(db)
        for call in (w.refire(1, 1.0), w.undelivered(1, 1.0, 1.0), w.claim(1, 1.0), w.delivered(1, True),
                     w.dismiss(1, 1, 1)):
            with pytest.raises(WakesUnavailable):
                await call

    run(go())


def test_nothing_of_a_reminder_reaches_a_log_through_delivery_calls(home: Home, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley import logs

    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        async with wakes(home.url) as w:
            a = await fire(w, home, "scheduled")
            await w.refire(a, 0.0)
            b = await fire(w, home, "sending")
            await w.undelivered(10, 0.0, 86400.0)
            await w.delivered(b, False)
            await w.dismiss(home.one, home.alana, b)
            await asyncio.sleep(0.2)
            await w.prune(0.1)

    run(go())
    out = capsys.readouterr()
    assert "PLANTED" not in out.out + out.err and "500 dollars" not in out.out + out.err


@pytest.mark.parametrize("state", ["sending", "undelivered"])
def test_a_dismissed_reminder_is_not_handed_out_for_another_push(home: Home, state: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, state)
            assert await w.dismiss(home.one, home.alana, id_) is True
            assert await w.undelivered(10, 0.0, 86400.0) == ()

    run(go())


@pytest.mark.parametrize("state", ["sending", "undelivered"])
def test_claim_gives_one_caller_the_try_and_times_it(home: Home, state: str) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            id_ = await fire(w, home, state)
            assert await w.claim(id_, 300.0) is (state == "sending")
            assert await w.claim(id_, 0.0) is True
            assert await w.claim(id_, 300.0) is False
            assert await w.undelivered(10, 300.0, 86400.0) == ()

    run(go())


def test_claim_races_to_one_winner(home: Home) -> None:
    async def go() -> None:
        dbs = [PoolDatabase(home.url, connect_timeout_s=5.0) for _ in range(4)]
        for db in dbs:
            await db.open()
        try:
            async with wakes(home.url) as w:
                id_ = await fire(w, home, "sending")
            got = await asyncio.gather(*(PostgresWakes(db).claim(id_, 300.0) for db in dbs))
            assert sorted(got) == [False, False, False, True]
        finally:
            for db in dbs:
                await db.close()

    run(go())


def test_claim_refuses_what_is_dismissed_delivered_unfired_or_missing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            dismissed = await fire(w, home, "undelivered")
            await w.dismiss(home.one, home.alana, dismissed)
            ids = [dismissed, await fire(w, home, "delivered"), await fire(w, home, "scheduled"),
                   await fire(w, home, "failed"), 999999]
            for id_ in ids:
                assert await w.claim(id_, 0.0) is False

    run(go())
