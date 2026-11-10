"""The `Deposits` service on a real database: arming stores an unsettled reminder that is never due and is listed with
its rule; `fire` stores one ordinary reminder per (armed reminder, transaction), once, from any caller; the read-through
cursor only moves forward, per household."""

import asyncio
from datetime import date, timedelta

import pytest
from ashley.senses.deposits import DepositsUnavailable, NullDeposits
from ashley.senses.wakes import Reminder
from contract.conversations_support import run
from ds_support import ARMED_AT, BRIEF, CHECKING, SAVINGS, home, rule


def test_arming_lists_the_reminder_with_its_rule_household_and_the_instant_it_was_set(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            made = rule(min_cents=500, payee="Acme", match="exact")
            armed_id = await f.arm(made)
            (a,) = await f.armed()
            assert (a.id, a.household_id, a.rule, a.armed_at) == (armed_id, f.house, made, ARMED_AT)
            (listed,) = [s for s in await f.wakes.reminders(f.house, f.alana) if s.id == armed_id]
            assert listed.deposit == made and listed.state == "scheduled" and listed.reminder.brief == BRIEF

    run(go())


def test_armed_reminders_are_listed_oldest_first_and_keep_their_own_rules(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            first = await f.arm(rule(CHECKING, 100), at=ARMED_AT)
            second = await f.arm(rule(SAVINGS, 200), at=ARMED_AT + timedelta(days=1))
            assert [(a.id, a.rule.account_id) for a in await f.armed()] == [(first, CHECKING), (second, SAVINGS)]

    run(go())


def test_an_armed_reminder_is_never_due_however_long_ago_it_was_set(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(), at=ARMED_AT - timedelta(days=400))
            assert await f.wakes.due(10) == ()

    run(go())


@pytest.mark.parametrize("brief,repeat", [("", False), ("x" * 501, False), ("bad\x00brief", False), (BRIEF, True)])
def test_arming_refuses_a_bad_brief_or_a_repeat_and_stores_nothing(db_url: str, brief: str, repeat: bool) -> None:
    from ashley.senses.repeat import Repeat

    async def go() -> None:
        async with home(db_url) as f:
            again = Repeat("daily", 1, ARMED_AT.replace(tzinfo=None)) if repeat else None
            with pytest.raises(ValueError):
                await f.deposits.arm(Reminder(f.house, f.alana, f.alana, brief, ARMED_AT, again), rule())
            assert await f.armed() == ()

    run(go())


def test_the_longest_brief_is_accepted(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(), brief="x" * 500)
            assert len(await f.armed()) == 1

    run(go())


def test_a_fire_stores_one_due_reminder_for_the_person_and_asker_and_the_same_transaction_only_once(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            armed_id = await f.arm(rule(), who=f.sam, made_by=f.alana, brief="split the bonus")
            assert await f.deposits.fire(armed_id, "tx-1") is True
            assert await f.deposits.fire(armed_id, "tx-1") is False
            (one,) = await f.fired(f.sam)
            assert (one.reminder.brief, one.reminder.person_id, one.reminder.made_by) == ("split the bonus", f.sam, f.alana)
            assert one.reminder.repeat is None
            assert len(await f.wakes.due(10)) == 1
            assert [a.id for a in await f.armed()] == [armed_id]

    run(go())


def test_a_different_transaction_fires_again_and_the_armed_reminder_stays_armed(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            armed_id = await f.arm(rule())
            assert [await f.deposits.fire(armed_id, t) for t in ("tx-1", "tx-2", "tx-1", "tx-3")] == [True, True, False, True]
            assert len(await f.fired()) == 3
            assert len(await f.armed()) == 1

    run(go())


def test_one_transaction_fires_each_armed_reminder_that_names_it(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            one, two = await f.arm(rule(), brief="one"), await f.arm(rule(), brief="two")
            assert await f.deposits.fire(one, "tx-1") and await f.deposits.fire(two, "tx-1")
            assert sorted(s.reminder.brief for s in await f.fired()) == ["one", "two"]

    run(go())


def test_many_callers_firing_at_once_store_one_and_exactly_one_is_told_so(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            armed_id = await f.arm(rule())
            got = await asyncio.gather(*[f.deposits.fire(armed_id, "tx-1") for _ in range(8)])
            assert sorted(got) == [False] * 7 + [True]
            assert len(await f.fired()) == 1

    run(go())


def test_a_cancelled_or_unknown_armed_reminder_fires_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            armed_id = await f.arm(rule())
            assert await f.wakes.cancel(f.house, f.alana, armed_id)
            assert await f.armed() == ()
            assert await f.deposits.fire(armed_id, "tx-1") is False
            assert await f.deposits.fire(armed_id + 1000, "tx-1") is False
            assert await f.fired() == []

    run(go())


def test_the_read_through_day_is_none_until_set_and_never_moves_back(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            assert await f.deposits.read_through(f.house) is None
            await f.deposits.advance(f.house, date(2026, 10, 22))
            assert await f.deposits.read_through(f.house) == date(2026, 10, 22)
            await f.deposits.advance(f.house, date(2026, 10, 25))
            assert await f.deposits.read_through(f.house) == date(2026, 10, 25)
            await f.deposits.advance(f.house, date(2026, 10, 23))
            assert await f.deposits.read_through(f.house) == date(2026, 10, 25)
            await f.deposits.advance(f.house, date(2026, 10, 25))
            assert await f.deposits.read_through(f.house) == date(2026, 10, 25)

    run(go())


def test_the_read_through_day_is_each_households_own(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            house2, _ = f.add_house("two", "https://two.test")
            await f.deposits.advance(f.house, date(2026, 10, 22))
            assert await f.deposits.read_through(house2) is None
            await f.deposits.advance(house2, date(2026, 10, 1))
            assert await f.deposits.read_through(f.house) == date(2026, 10, 22)
            assert await f.deposits.read_through(house2) == date(2026, 10, 1)

    run(go())


def test_the_reminders_of_two_households_are_armed_apart(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            house2, who2 = f.add_house("two", "https://two.test")
            await f.arm(rule())
            await f.deposits.arm(Reminder(house2, who2, who2, "theirs", ARMED_AT, None), rule(SAVINGS, 7))
            assert sorted(a.household_id for a in await f.armed()) == sorted([f.house, house2])
            assert await f.wakes.reminders(house2, f.alana) == ()

    run(go())


def test_an_unwired_process_sees_a_deposits_that_raises_not_one_that_drops_a_deposit(db_url: str) -> None:
    async def go() -> None:
        null = NullDeposits()
        with pytest.raises(DepositsUnavailable):
            await null.armed()
        with pytest.raises(DepositsUnavailable):
            await null.fire(1, "t")
        with pytest.raises(DepositsUnavailable):
            await null.read_through(1)

    run(go())
