"""The deposit sense (`ashley.senses.deposit_sense`) on a real database against a fake Sure: a matching deposit stores one
once reminder; a non-match stores none; a retry, a second reader or a new holder with no memory stores none again; a
deposit that lands while nobody reads is found by the next poll; a cursor survives a poll that failed; the armed
reminder stays armed and fires on the next match; a cancelled one never fires; and no log line carries an amount,
payee or account name."""

from dataclasses import replace
from datetime import date, timedelta

import psycopg
from ashley import logs
from ashley.senses import deposit_sense, ledger_transactions
from ashley.senses.deposits import DepositsUnavailable
from ashley.senses.deposit_rule import Landed
from ashley.senses.wakes import Reminder
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from deposit_support import BONUS, NOW, SAVINGS, DepositSure, deposit, house, rule
from money_support import CHECKING
import pytest


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

DAY = date(2026, 11, 3)


def fired(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM wakes WHERE kind = 'reminder' AND trigger = 'time'"))


def test_a_matching_deposit_fires_once_however_often_it_is_read(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", 250_000, DAY, merchant=BONUS)])
        async with house(db_url, sure) as h:
            armed = await h.arm(rule())
            await deposit_sense.poll(NOW)
            await deposit_sense.poll(NOW)
            await deposit_sense.poll(NOW + timedelta(hours=1))
            assert fired(db_url) == 1
            (due,) = await h.wakes.due(10)
            assert isinstance(due.wake, Reminder) and due.wake.brief == "Your bonus landed: move it to joint savings."
            assert due.wake.landed == Landed(250_000, DAY, "Checking", BONUS)
            assert await h.deposits.armed() != ()
            assert armed not in {d.id for d in await h.wakes.due(10)}

    run(go())


@pytest.mark.parametrize("row", [
    deposit("t1", "ACH credit", 99_999, DAY, merchant=BONUS),
    deposit("t2", "ACH credit", 250_000, DAY, merchant="Someone Else"),
    deposit("t3", "ACH credit", 250_000, DAY, merchant=BONUS, account_id=SAVINGS),
    deposit("t4", "ACH credit", 250_000, DAY, merchant=BONUS, classification="expense"),
    deposit("t5", "ACH credit", 250_000, DAY, merchant=BONUS, transfer=True),
    deposit("t6", "ACH credit", 250_000, date(2026, 10, 1), merchant=BONUS),
], ids=["below-minimum", "other-payee", "other-account", "expense", "transfer", "before-it-was-set"])
def test_a_deposit_that_does_not_match_fires_nothing(db_url: str, row: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure(rows=[row])) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 0 and len(h.sure.polls()) == 1

    run(go())


def test_the_payee_is_matched_as_the_rule_says(db_url: str) -> None:
    async def go() -> None:
        rows = [deposit("t1", "payroll", 250_000, DAY, merchant="Acme Corp Bonus")]
        async with house(db_url, DepositSure(rows=rows)) as h:
            await h.arm(rule(payee="Acme", payee_match="exact"))
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 0
            await h.arm(rule(payee="acme corp bonus", payee_match="exact"))
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 1

    run(go())


def test_a_new_holder_with_no_memory_and_a_second_reader_fire_nothing_twice(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", 250_000, DAY, merchant=BONUS)])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("DELETE FROM deposit_reads")
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 1
            (armed,) = await h.deposits.armed()
            assert await h.deposits.fire(armed.id, "t1") is False
            assert await h.deposits.fire(armed.id, "t2") is True

    run(go())


def test_a_deposit_that_lands_while_nobody_reads_is_found_by_the_next_holder(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure()
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 0
            sure.rows.append(deposit("t1", "ACH credit", 250_000, DAY + timedelta(days=1), merchant=BONUS))
            await deposit_sense.poll(NOW + timedelta(days=9))
            assert fired(db_url) == 1
            assert await h.deposits.read_through(h.home) == (NOW + timedelta(days=9)).date()
            starts = [q["start_date"] for q in sure.polls()]
            assert starts == [(DAY - timedelta(days=1)).isoformat()] * 2

    run(go())


def test_a_poll_that_could_not_read_sure_moves_nothing_and_the_next_reads_it_all(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", 250_000, DAY, merchant=BONUS)])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            sure.status = 503
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 0 and await h.deposits.read_through(h.home) is None
            sure.status = 200
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 1 and await h.deposits.read_through(h.home) == DAY

    run(go())


def test_an_armed_reminder_fires_on_every_match_and_a_cancelled_one_on_none(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", 250_000, DAY, merchant=BONUS)])
        async with house(db_url, sure) as h:
            armed = await h.arm(rule())
            await deposit_sense.poll(NOW)
            sure.rows.append(deposit("t2", "ACH credit", 400_000, DAY, merchant=BONUS))
            await deposit_sense.poll(NOW + timedelta(hours=1))
            assert fired(db_url) == 2
            assert await h.wakes.cancel(h.home, h.alana, armed) is True
            sure.rows.append(deposit("t3", "ACH credit", 400_000, DAY, merchant=BONUS))
            await deposit_sense.poll(NOW + timedelta(hours=2))
            assert fired(db_url) == 2 and await h.deposits.armed() == ()

    run(go())


def test_a_household_with_no_armed_reminder_is_never_read(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await deposit_sense.poll(NOW)
            assert h.sure.seen == []

    run(go())


def test_the_cursor_never_moves_back(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await h.deposits.advance(h.home, DAY)
            await h.deposits.advance(h.home, DAY - timedelta(days=5))
            assert await h.deposits.read_through(h.home) == DAY

    run(go())


def test_the_database_gone_is_unavailable(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await h.arm(rule())
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("ALTER TABLE deposit_reads RENAME TO gone")
            with pytest.raises(DepositsUnavailable):
                await deposit_sense.poll(NOW)

    run(go())


def test_logs_carry_counts_and_ids_never_what_was_paid(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", 250_000, DAY, merchant=BONUS)])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)

    run(go())
    out = capsys.readouterr().out
    assert "event=deposits.poll" in out and "read=1 matched=1 fired=1" in out and "event=deposits.fired" in out
    for secret in ("Acme", "2500", "250000", "Checking", CHECKING, "the-households-test-key"):
        assert secret not in out


def test_a_deposit_dated_before_the_last_read_but_posted_after_it_is_still_found(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure()
        async with house(db_url, sure) as h:
            await h.arm(rule(), at=NOW - timedelta(days=10))
            await deposit_sense.poll(NOW)
            sure.rows.append(deposit("late", "ACH credit", 250_000, DAY - timedelta(days=2), merchant=BONUS))
            sure.rows.append(deposit("old", "ACH credit", 250_000, DAY - timedelta(days=6), merchant=BONUS))
            await deposit_sense.poll(NOW + timedelta(hours=1))
            assert fired(db_url) == 1

    run(go())


def test_a_deposit_with_no_merchant_is_matched_by_its_own_name_and_an_excluded_transfer_in_is_not(db_url: str) -> None:
    async def go() -> None:
        excluded = deposit("t2", "ACME TRANSFER", 250_000, DAY, transfer=True)
        excluded["excluded"] = True
        sure = DepositSure(rows=[deposit("t1", "ACME CORP PAYROLL", 250_000, DAY), excluded])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 1

    run(go())


def test_a_read_cut_short_by_max_pages_continues_from_where_it_stopped(db_url: str,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    small = replace(deposit_sense.CONFIG, per_page=1, max_pages=2, lookback_days=1)
    monkeypatch.setattr(deposit_sense, "CONFIG", small)
    monkeypatch.setattr(ledger_transactions, "CONFIG", small)

    async def go() -> None:
        days = [DAY - timedelta(days=n) for n in (8, 6, 2, 0)]
        sure = DepositSure(rows=[deposit(f"t{n}", "ACME CORP PAYROLL", 250_000, d) for n, d in enumerate(days)])
        async with house(db_url, sure) as h:
            await h.arm(rule(), at=NOW - timedelta(days=10))
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 2 and await h.deposits.read_through(h.home) == days[1]
            await deposit_sense.poll(NOW)
            await deposit_sense.poll(NOW)
            assert fired(db_url) == 4

    run(go())
