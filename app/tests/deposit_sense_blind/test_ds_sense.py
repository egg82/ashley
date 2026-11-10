"""The deposit sense through `poll`: a deposit into the household's Sure that a rule waits for stores one reminder,
once; the ones it must not match store nothing; the cursor in Postgres means the next holder finds what landed while
none ran; nothing about a deposit is logged."""

import asyncio
from datetime import date, datetime, timedelta

import pytest
from ashley import logs
from ashley.senses.deposit_sense import poll
from ashley.senses.wakes import Reminder
from contract.conversations_support import run
from ds_support import (ARMED_AT, ARMED_DAY, BONUS, BRIEF, CHECKING, NOW, SAVINGS, Folks, days_ago, home, rule, transfer_in, tx)


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

LATER = NOW + timedelta(days=9)


async def count_fired(f: Folks) -> int:
    return len(await f.fired())


def test_a_matching_deposit_fires_one_reminder_with_the_armed_ones_person_and_brief(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=10000), who=f.sam, made_by=f.alana)
            f.put(tx("t1", ARMED_DAY + timedelta(days=1), 25000))
            await poll(NOW)
            (one,) = await f.fired(f.sam)
            assert one.reminder.brief == BRIEF
            assert (one.reminder.person_id, one.reminder.made_by, one.reminder.household_id) == (f.sam, f.alana, f.house)
            assert one.reminder.repeat is None
            assert len(await f.wakes.due(10)) == 1

    run(go())


def test_the_same_deposit_read_by_later_polls_fires_once(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule())
            f.put(tx("t1", ARMED_DAY + timedelta(days=1), 25000))
            for hours in (0, 1, 30, 80):
                await poll(NOW + timedelta(hours=hours))
            assert await count_fired(f) == 1

    run(go())


def test_a_deposit_below_the_minimum_does_not_fire_and_one_at_it_does(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=10000))
            f.put(tx("small", ARMED_DAY + timedelta(days=1), 9999))
            await poll(NOW)
            assert await count_fired(f) == 0
            assert f.sure.calls, "the sense never read Sure, so nothing proves the deposit was seen and refused"
            f.put(tx("exact", ARMED_DAY + timedelta(days=1), 10000))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_deposit_into_another_account_does_not_fire(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(account=CHECKING))
            f.put(tx("elsewhere", ARMED_DAY + timedelta(days=1), 50000, account=SAVINGS))
            await poll(NOW)
            assert await count_fired(f) == 0
            f.put(tx("here", ARMED_DAY + timedelta(days=1), 50000, account=CHECKING))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_an_exact_payee_matches_the_whole_name_only_whatever_the_case(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=None, payee="Acme Payroll", match="exact"))
            day = ARMED_DAY + timedelta(days=1)
            f.put(tx("longer", day, 50000, merchant="Acme Payroll Inc"), tx("shorter", day, 50000, merchant="Acme"),
                  tx("other", day, 50000, merchant="Globex"))
            await poll(NOW)
            assert await count_fired(f) == 0
            f.put(tx("same", day, 50000, merchant="ACME payroll"))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_contains_payee_matches_inside_the_name_whatever_the_case(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=None, payee="payroll", match="contains"))
            day = ARMED_DAY + timedelta(days=1)
            f.put(tx("nope", day, 50000, merchant="Globex"))
            await poll(NOW)
            assert await count_fired(f) == 0
            f.put(tx("yes", day, 50000, merchant="ACME PAYROLL LLC"))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_deposit_with_no_merchant_is_matched_by_its_own_name(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=None, payee=BONUS, match="exact"))
            f.put(tx("named", ARMED_DAY + timedelta(days=1), 50000, name=BONUS))
            await poll(NOW)
            assert await count_fired(f) == 1

    run(go())


def test_a_payee_and_a_minimum_must_both_hold(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100000, payee="Acme", match="contains"))
            day = ARMED_DAY + timedelta(days=1)
            f.put(tx("rich-stranger", day, 500000, merchant="Globex"), tx("poor-acme", day, 5000, merchant="Acme"))
            await poll(NOW)
            assert await count_fired(f) == 0
            f.put(tx("both", day, 500000, merchant="Acme"))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


@pytest.mark.parametrize("marked", ["both", "excluded", "transfer"])
def test_a_transfer_in_never_fires_though_it_is_income(db_url: str, marked: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100))
            day = ARMED_DAY + timedelta(days=1)
            moved = {"both": transfer_in("move", day, 900000),
                     "excluded": tx("move", day, 900000, name="Transfer from Savings", excluded=True),
                     "transfer": tx("move", day, 900000, name="Transfer from Savings", transfer=True)}[marked]
            f.put(moved, tx("pay", day, 20000))
            await poll(NOW)
            assert [s.reminder.brief for s in await f.fired()] == [BRIEF]
            assert len(f.sure.rows[f.base]) == 2

    run(go())


def test_an_expense_and_a_split_parent_never_fire(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100))
            day = ARMED_DAY + timedelta(days=1)
            f.put(tx("spend", day, 900000, kind="expense"), tx("parent", day, 900000, split_parent=True))
            await poll(NOW)
            assert await count_fired(f) == 0
            assert f.sure.calls
            f.put(tx("refund", day, 900000, merchant="Store"))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_deposit_from_before_the_reminder_was_set_never_fires(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100))
            f.put(tx("old", ARMED_DAY - timedelta(days=1), 90000), tx("older", ARMED_DAY - timedelta(days=40), 90000),
                  tx("same-day", ARMED_DAY, 91000))
            await poll(NOW)
            await poll(LATER)
            assert len(await f.fired()) == 1

    run(go())


def test_the_day_a_reminder_was_set_is_the_households_local_day(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            late = datetime(2026, 10, 21, 2, 0, tzinfo=ARMED_AT.tzinfo)  # Oct 20, 20:00 in Denver
            await f.arm(rule(min_cents=100), at=late)
            f.put(tx("eve", date(2026, 10, 19), 90000))
            await poll(NOW)
            assert await count_fired(f) == 0
            f.put(tx("local-day", date(2026, 10, 20), 90000))
            await poll(NOW + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_first_read_goes_back_to_the_day_the_reminder_was_set_not_only_the_lookback(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100))
            f.put(tx("week-old", ARMED_DAY + timedelta(days=1), 90000))
            await poll(LATER)
            assert await count_fired(f) == 1

    run(go())


def test_a_deposit_fires_only_the_reminders_that_were_set_by_its_day(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(), brief="set on the 20th", at=ARMED_AT)
            await f.arm(rule(), brief="set on the 22nd", at=ARMED_AT + timedelta(days=2))
            f.put(tx("t1", ARMED_DAY + timedelta(days=1), 25000))
            await poll(NOW)
            assert [s.reminder.brief for s in await f.fired()] == ["set on the 20th"]

    run(go())


def test_an_armed_reminder_fires_on_every_later_match_until_cancelled(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            armed_id = await f.arm(rule())
            f.put(tx("bonus-1", ARMED_DAY + timedelta(days=1), 25000))
            await poll(NOW)
            f.put(tx("bonus-2", ARMED_DAY + timedelta(days=2), 25000))
            await poll(NOW + timedelta(days=1))
            f.put(tx("bonus-3", ARMED_DAY + timedelta(days=3), 25000))
            await poll(NOW + timedelta(days=2))
            assert await count_fired(f) == 3
            assert [a.id for a in await f.armed()] == [armed_id]
            assert await f.wakes.cancel(f.house, f.alana, armed_id)
            f.put(tx("bonus-4", ARMED_DAY + timedelta(days=4), 25000))
            await poll(NOW + timedelta(days=3))
            assert await count_fired(f) == 3

    run(go())


def test_each_armed_reminder_fires_for_a_deposit_it_matches_and_only_those(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=10000), brief="first brief")
            await f.arm(rule(min_cents=1000000), brief="second brief")
            f.put(tx("t1", ARMED_DAY + timedelta(days=1), 25000))
            await poll(NOW)
            assert [s.reminder.brief for s in await f.fired()] == ["first brief"]

    run(go())


def test_the_cursor_lets_the_next_holder_find_what_landed_while_none_ran(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule())
            await poll(NOW)
            read = await f.deposits.read_through(f.house)
            assert read is not None and date(2026, 10, 21) <= read <= date(2026, 10, 22)
            f.put(tx("while-away", ARMED_DAY + timedelta(days=4), 25000))
            assert days_ago(0, LATER) - (ARMED_DAY + timedelta(days=4)) > timedelta(days=3)
            await poll(LATER)
            assert await count_fired(f) == 1
            await poll(LATER + timedelta(days=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_poll_with_no_armed_reminder_reads_nothing_and_a_poll_with_one_records_the_day(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await poll(NOW)
            assert f.sure.calls == []
            assert await f.deposits.read_through(f.house) is None
            await f.arm(rule())
            await poll(NOW)
            assert f.sure.calls
            assert await f.deposits.read_through(f.house) is not None

    run(go())


def test_a_sure_that_cannot_be_read_fires_nothing_keeps_the_cursor_and_is_read_whole_next_time(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule())
            await poll(NOW)
            before = await f.deposits.read_through(f.house)
            f.put(tx("during-outage", ARMED_DAY + timedelta(days=4), 25000))
            f.sure.down = True
            await poll(LATER)
            assert await count_fired(f) == 0
            assert await f.deposits.read_through(f.house) == before
            f.sure.down = False
            await poll(LATER + timedelta(hours=1))
            assert await count_fired(f) == 1

    run(go())


def test_a_household_without_sure_connected_is_passed_over_and_the_next_one_still_read(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url, with_sure=False) as f:
            await f.arm(rule())
            house2, who2 = f.add_house("two", "https://money.two.test")
            await f.deposits.arm(Reminder(house2, who2, who2, "two's brief", ARMED_AT, None), rule())
            f.put(tx("t", ARMED_DAY + timedelta(days=1), 25000), base="https://money.two.test")
            await poll(NOW)
            assert await count_fired(f) == 0
            assert [s.reminder.brief for s in await f.wakes.reminders(house2, who2) if s.deposit is None] == ["two's brief"]

    run(go())


def test_one_households_deposit_never_fires_another_households_reminder(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            house2, who2 = f.add_house("two", "https://money.two.test")
            await f.arm(rule())
            await f.deposits.arm(Reminder(house2, who2, who2, "two's brief", ARMED_AT, None), rule())
            f.put(tx("only-two", ARMED_DAY + timedelta(days=1), 25000), base="https://money.two.test")
            await poll(NOW)
            assert await count_fired(f) == 0
            assert len([s for s in await f.wakes.reminders(house2, who2) if s.deposit is None]) == 1

    run(go())


def test_two_polls_at_once_fire_one_reminder(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule())
            f.put(tx("t1", ARMED_DAY + timedelta(days=1), 25000))
            f.sure.yields = 4
            await asyncio.gather(poll(NOW), poll(NOW), poll(NOW))
            assert await count_fired(f) == 1

    run(go())


def test_a_transaction_a_rule_cannot_judge_is_skipped_and_the_rest_still_fire(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule())
            day = ARMED_DAY + timedelta(days=1)
            no_id = tx("x", day, 25000)
            no_id["id"] = None
            no_amount = tx("y", day, 25000)
            no_amount["signed_amount_cents"] = None
            bad_date = tx("z", day, 25000)
            bad_date["date"] = "not a date"
            f.put(no_id, no_amount, bad_date, tx("good", day, 25000))
            await poll(NOW)
            assert await count_fired(f) == 1

    run(go())


def test_a_deposit_past_the_first_page_is_found(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100000))
            day = ARMED_DAY + timedelta(days=1)
            f.put(*[tx(f"small-{n}", day, 500) for n in range(130)], tx("big", day, 500000))
            await poll(NOW)
            assert await count_fired(f) == 1

    run(go())


def test_nothing_about_a_deposit_reaches_a_log(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        async with home(db_url) as f:
            await f.arm(rule(min_cents=100, payee=BONUS, match="exact"))
            day = ARMED_DAY + timedelta(days=1)
            f.put(tx("t1", day, 987654, merchant=BONUS), tx("t2", day, 987655, merchant="Globex-Planted-zq"))
            await poll(NOW)
            f.sure.down = True
            await poll(NOW + timedelta(hours=2))
            assert await count_fired(f) == 1

    run(go())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "deposits.poll" in text and "deposits.fired" in text and "deposits.unreadable" in text
    for secret in ("Planted", "987654", "987655", "9876.54", "9,876.54", BRIEF, "Acme"):
        assert secret not in text, secret
