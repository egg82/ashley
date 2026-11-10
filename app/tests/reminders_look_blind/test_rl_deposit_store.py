"""A deposit's reminder stores what landed: `Deposits.fire(armed_id, transaction_id, landed=None)` keeps `landed` on the
once reminder it stores (`wakes.landed`), once per transaction, whoever asks and however often; old call sites that give
none store none; the deposit sense gives the fields Sure reported."""

import asyncio
import json
from datetime import timedelta

import pytest
from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import Landed, landed_from_json
from ashley.senses.deposits import DepositsUnavailable, NullDeposits
from ashley.senses.wakes import Reminder
from contract.conversations_support import run, scalar
from deposit_support import BONUS, NOW, House, DepositSure, deposit, house, rule
from reminders_look_blind_support import ACCOUNT, DAY, LANDED


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

NOTE = "move the bonus"


def rows(url: str, where: str = "kind = 'reminder' AND trigger = 'time'") -> int:
    return int(scalar(url, f"SELECT count(*) FROM wakes WHERE {where}"))


def stored(url: str) -> list[Landed | None]:
    import psycopg
    with psycopg.connect(url) as conn:
        found = conn.execute("SELECT landed FROM wakes WHERE kind = 'reminder' AND trigger = 'time' ORDER BY id").fetchall()
    return [None if r[0] is None else landed_from_json(json.loads(r[0]) if isinstance(r[0], str) else r[0]) for r in found]


async def reminders_due(h: House) -> list[Reminder]:
    return [d.wake for d in await h.wakes.due(50) if isinstance(d.wake, Reminder)]


def test_a_fire_stores_the_deposit_it_was_given(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            assert await h.deposits.fire(armed, "tx-1", LANDED) is True
            (one,) = await reminders_due(h)
            assert one.landed == LANDED
            assert stored(db_url) == [LANDED]

    run(go())


def test_the_old_call_with_no_landed_stores_none_and_the_rest_as_before(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule(), brief=NOTE)
            assert await h.deposits.fire(armed, "tx-1") is True
            (one,) = await reminders_due(h)
            assert one.landed is None and one.brief == NOTE and one.repeat is None
            assert stored(db_url) == [None]

    run(go())


def test_landed_may_be_passed_by_keyword_or_position(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            assert await h.deposits.fire(armed, "a", landed=LANDED) is True
            assert await h.deposits.fire(armed, "b", None) is True
            assert sorted(stored(db_url), key=lambda x: x is None) == [LANDED, None]

    run(go())


def test_the_same_transaction_fired_twice_stores_once_with_the_first_landed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            other = Landed(1, DAY + timedelta(days=1), "Other", "Other Payer")
            assert await h.deposits.fire(armed, "tx-1", LANDED) is True
            assert await h.deposits.fire(armed, "tx-1", other) is False
            assert await h.deposits.fire(armed, "tx-1") is False
            assert rows(db_url) == 1 and stored(db_url) == [LANDED]

    run(go())


def test_a_retry_with_none_after_a_fire_does_not_blank_what_landed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            await h.deposits.fire(armed, "tx-1", LANDED)
            await h.deposits.fire(armed, "tx-1", None)
            assert stored(db_url) == [LANDED]

    run(go())


def test_each_transaction_keeps_its_own_landed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            first, second = LANDED, Landed(5_00, DAY + timedelta(days=2), ACCOUNT, None)
            await h.deposits.fire(armed, "tx-1", first)
            await h.deposits.fire(armed, "tx-2", second)
            assert sorted(stored(db_url), key=lambda x: x.cents if x else 0) == [second, first]
            assert sorted(r.landed.cents for r in await reminders_due(h) if r.landed) == [500, LANDED.cents]

    run(go())


def test_readers_racing_for_one_transaction_store_it_once(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            tries = [Landed(i, DAY, ACCOUNT, f"P{i}") for i in range(1, 9)]
            won = await asyncio.gather(*(h.deposits.fire(armed, "tx-1", t) for t in tries))
            assert sum(won) == 1 and rows(db_url) == 1
            (kept,) = stored(db_url)
            assert kept in tries

    run(go())


def test_firing_leaves_the_armed_reminder_armed_and_without_a_deposit_of_its_own(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            await h.deposits.fire(armed, "tx-1", LANDED)
            assert [a.id for a in await h.deposits.armed()] == [armed]
            assert rows(db_url, "trigger = 'event'") == 1
            assert int(scalar(db_url, "SELECT count(*) FROM wakes WHERE trigger = 'event' AND landed IS NOT NULL")) == 0

    run(go())


def test_an_armed_reminder_that_was_cancelled_stores_nothing_whatever_it_is_given(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            assert await h.wakes.cancel(h.home, h.alana, armed) is True
            assert await h.deposits.fire(armed, "tx-1", LANDED) is False
            assert await h.deposits.fire(armed + 999, "tx-1", LANDED) is False
            assert rows(db_url) == 0

    run(go())


def test_a_reminder_not_fired_by_a_deposit_has_none(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            from datetime import UTC, datetime
            await h.wakes.schedule(Reminder(h.home, h.alana, h.alana, "pay rent", datetime.now(UTC) - timedelta(seconds=5), None))
            (one,) = await reminders_due(h)
            assert one.landed is None
            assert int(scalar(db_url, "SELECT count(*) FROM wakes WHERE landed IS NOT NULL")) == 0

    run(go())


@pytest.mark.parametrize("payee", ["O'Brien \"Sons\"", "日本語 🎉", "x" * 5000, "'; DROP TABLE wakes;--", '{"cents": 1}',
                                   "line\nbreak", "back\\slash", "", None])
def test_whatever_the_payee_it_is_stored_and_read_back_as_it_was(db_url: str, payee: str | None) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            want = Landed(1234, DAY, "Acct \"1\"", payee)
            assert await h.deposits.fire(armed, "tx-1", want) is True
            (one,) = await reminders_due(h)
            assert one.landed == want

    run(go())


def test_a_payee_postgres_cannot_hold_does_not_break_the_caller_with_a_foreign_error(db_url: str) -> None:
    """A NUL in a name cannot be stored as JSON; the service says `DepositsUnavailable` or stores something, never a raw
    driver error that would fail every poll that reads that deposit again."""
    async def go() -> None:
        async with house(db_url) as h:
            armed = await h.arm(rule())
            try:
                await h.deposits.fire(armed, "tx-1", Landed(100, DAY, "Acct", "Acme\x00Corp"))
            except DepositsUnavailable:
                pass

    run(go())


def test_the_null_service_refuses_a_fire_with_landed_as_it_does_one_without() -> None:
    async def go() -> None:
        for fire in (NullDeposits().fire(1, "tx", LANDED), NullDeposits().fire(1, "tx")):
            with pytest.raises(DepositsUnavailable):
                await fire

    run(go())


def test_the_sense_gives_the_reminder_the_deposit_sure_reported(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH credit", 250_000, DAY, merchant=BONUS)])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            assert stored(db_url) == [Landed(250_000, DAY, "Checking", BONUS)]

    run(go())


def test_with_no_merchant_the_payee_is_the_transactions_own_name(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "Acme Payroll Direct", 250_000, DAY)])
        async with house(db_url, sure) as h:
            await h.arm(rule(payee=None))
            await deposit_sense.poll(NOW)
            assert stored(db_url) == [Landed(250_000, DAY, "Checking", "Acme Payroll Direct")]

    run(go())


def test_the_deposit_stored_is_the_one_that_matched_when_others_do_not(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH", 99_999, DAY, merchant=BONUS),
                                 deposit("t2", "ACH", 250_000, DAY - timedelta(days=0), merchant=BONUS),
                                 deposit("t3", "ACH", 400_000, DAY, merchant="Someone Else")])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            assert stored(db_url) == [Landed(250_000, DAY, "Checking", BONUS)]

    run(go())


def test_two_deposits_each_fire_with_their_own_fields_and_a_second_poll_changes_nothing(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH", 250_000, DAY, merchant=BONUS),
                                 deposit("t2", "ACH", 300_000, DAY + timedelta(days=1), merchant=BONUS + " Two")])
        async with house(db_url, sure) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW + timedelta(days=3))
            await deposit_sense.poll(NOW + timedelta(days=3, hours=1))
            got = sorted((x for x in stored(db_url) if x), key=lambda x: x.cents)
            assert got == [Landed(250_000, DAY, "Checking", BONUS),
                           Landed(300_000, DAY + timedelta(days=1), "Checking", BONUS + " Two")]

    run(go())
