"""A money rule on a bill coming due (`DepositRule.due_days`): the deposit sense reads the ledger's repeating payments
while such a rule is armed and fires one reminder per bill and due date, from `due_days` before the day it is expected;
a second holder or a retry stores nothing twice; the next due date of the same bill fires again. Time is the `now` each
poll is handed."""

import asyncio
import json
import re
from datetime import date, timedelta

import pytest
from ashley import logs
from ashley.channels.wake.reminder_turn import said
from ashley.criteria.record import Transaction
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.senses import deposit_sense
from ashley.senses.deposit_config import CONFIG
from ashley.senses.deposit_rule import DepositRule, Landed, describe, from_json, landed_from_json, landed_to_json, matches, to_json
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from deposit_support import NOW, AnsweringTools, DepositSure, House, house
from money_support import CHECKING, account, page, recurring
from test_reminder_look import ALANA

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

THREE = DepositRule(CHECKING, "Checking", due_days=3)
BRIEF = "The internet bill is nearly due: check there is enough in Checking."
TODAY = NOW.date()
KEEP_DAYS = 7


def bills(h: House, *rows: dict[str, object]) -> None:
    h.sure.answers["/api/v1/recurring_transactions"] = {"recurring_transactions": list(rows), "pagination": page(len(rows))}


def on(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


async def fired(h: House) -> list[Reminder]:
    return [d.wake for d in await h.wakes.due(50) if isinstance(d.wake, Reminder)]


def test_it_fires_from_its_lead_once_per_due_date_and_again_for_the_next(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE, BRIEF)
            steps = [(0, 4, 0), (1, 4, 1), (2, 4, 1), (4, 4, 1), (5, 4, 1), (5, 34, 1), (30, 34, 1), (31, 34, 2)]
            for day, due, want in steps:
                bills(h, recurring("r1", "Internet", on(due)))
                await deposit_sense.poll(NOW + timedelta(days=day))
                assert len(await fired(h)) == want, (day, due)

    run(go())


def test_a_lead_of_zero_fires_on_the_day_itself_only(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(DepositRule(CHECKING, "Checking", due_days=0))
            for days, want in ((1, 0), (0, 1)):
                bills(h, recurring("r1", "Internet", on(days)))
                await deposit_sense.poll(NOW)
                assert len(await fired(h)) == want, days

    run(go())


def test_a_bill_whose_date_has_passed_without_firing_does_not_fire(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE)
            bills(h, recurring("r1", "Internet", on(-1)))
            await deposit_sense.poll(NOW)
            assert await fired(h) == []

    run(go())


def test_the_fired_reminder_carries_the_bill_and_her_turn_states_it(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE, BRIEF)
            bills(h, recurring("r1", "Internet", on(2), "59.99", autopay=True, merchant="Fibre Co"))
            await deposit_sense.poll(NOW)
            (reminder,) = await fired(h)
            assert (reminder.person_id, reminder.brief) == (h.alana, BRIEF)
            assert reminder.landed == Landed(5_999, TODAY + timedelta(days=2), "Checking", "Fibre Co", "out",
                                             due_in=2, autopay=True)
            text = said(reminder, ALANA, ALANA)
            assert f"59.99 to Fibre Co, out of Checking, expected in 2 day(s), on {on(2)}, and it pays itself" in text
            assert "deposit that landed" not in text

    run(go())


def test_only_the_bills_of_the_account_and_payee_that_are_still_expected_count(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(DepositRule(CHECKING, "Checking", payee="fibre", due_days=3), BRIEF)
            bills(h,
                  recurring("other-account", "Internet", on(1), account_id="a2", merchant="Fibre Co"),
                  recurring("other-payee", "Water", on(1)),
                  recurring("income", "Fibre refund", on(1), bill_type="income"),
                  recurring("ended", "Fibre old", on(1), status="inactive"),
                  recurring("no-date", "Fibre none", None),
                  recurring("bad-date", "Fibre odd", "soon"),
                  recurring("long-id-" + "x" * 80, "Fibre long", on(1)),
                  recurring("ok", "Internet", on(1), merchant="Fibre Co"))
            await deposit_sense.poll(NOW)
            (reminder,) = await fired(h)
            assert reminder.landed is not None and reminder.landed.payee == "Fibre Co"

    run(go())


def test_a_bill_sure_has_only_suggested_counts_and_so_does_one_it_calls_a_subscription(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE)
            bills(h, recurring("a", "Streaming", on(1), status="suggested", bill_type="subscription"),
                  recurring("b", "Rent", on(1), status="active"))
            await deposit_sense.poll(NOW)
            assert len(await fired(h)) == 2

    run(go())


def test_only_recurring_payments_are_read_while_only_bill_rules_are_armed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE)
            bills(h)
            await deposit_sense.poll(NOW)
            assert [p for p, _, _ in h.sure.seen] == ["/api/v1/recurring_transactions"]
            assert await h.deposits.read_through(h.home) is None

    run(go())


def test_recurring_payments_are_not_read_while_only_other_rules_are_armed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(DepositRule(CHECKING, "Checking", below_cents=100))
            await h.arm(DepositRule(CHECKING, "Checking", 100_000, "Acme"))
            await deposit_sense.poll(NOW)
            assert "/api/v1/recurring_transactions" not in {p for p, _, _ in h.sure.seen}

    run(go())


def test_a_bill_rule_a_balance_rule_and_a_transaction_rule_are_judged_in_one_poll(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE)
            await h.arm(DepositRule(CHECKING, "Checking", below_cents=20_000))
            h.sure.answers["/api/v1/accounts"] = {"accounts": [account(CHECKING, "Checking", "$10.00")],
                                                  "pagination": page(1)}
            bills(h, recurring("r1", "Internet", on(1)))
            await deposit_sense.poll(NOW)
            kinds = sorted(("bill" if r.landed.due_in is not None else "balance") for r in await fired(h)
                           if r.landed is not None)
            assert kinds == ["balance", "bill"]
            assert [p for p, _, _ in h.sure.seen if p == "/api/v1/transactions"] == []

    run(go())


def test_nothing_fires_when_the_ledger_cannot_be_read_and_the_next_poll_does(db_url: str,
                                                                              capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE)
            bills(h, recurring("r1", "Internet", on(1), "lots"))
            await deposit_sense.poll(NOW)
            assert await fired(h) == []
            bills(h, recurring("r1", "Internet", on(1)))
            await deposit_sense.poll(NOW + timedelta(minutes=5))
            assert len(await fired(h)) == 1

    run(go())
    assert "deposits.unreadable" in capsys.readouterr().out


def test_a_new_holder_with_no_memory_stores_no_second_reminder_for_one_bill(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            armed = await h.arm(THREE)
            bills(h, recurring("r1", "Internet", on(1)))
            await deposit_sense.poll(NOW)
            other = PoolDatabase(db_url, connect_timeout_s=5.0)
            await other.open()
            try:
                second = PostgresDeposits(other)
                due = Landed(1_200, TODAY + timedelta(days=1), "Checking", "Internet", "out", due_in=1)
                assert not await second.due(armed, "r1", due.day, due)
                got = await asyncio.gather(h.deposits.due(armed, "r2", due.day, due), second.due(armed, "r2", due.day, due))
                assert sorted(got) == [False, True]
            finally:
                await other.close()
            assert len(await fired(h)) == 2

    run(go())


def test_a_cancelled_rule_fires_nothing(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            armed = await h.arm(THREE)
            assert await h.wakes.cancel(h.home, h.alana, armed)
            assert not await h.deposits.due(armed, "r1", TODAY, Landed(1, TODAY, "Checking", "Internet", "out", due_in=0))
            assert await fired(h) == []

    run(go())


def test_the_poll_line_counts_bills_and_never_says_an_amount_or_a_name(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(THREE)
            bills(h, recurring("r1", "Fibre Internet", on(1), "123.45"))
            await deposit_sense.poll(NOW)

    run(go())
    out = "\n".join(line for line in re.sub(r"\b(ts|duration_ms)=\S+", "", capsys.readouterr().out).splitlines()
                    if "logger=ashley.senses.deposits" in line)
    assert "bills=1" in out and "billed=1" in out and "deposits.billed" in out
    assert not any(s in out for s in ("123", "12345", "Checking", "Fibre", "Internet"))


def test_the_rule_reads_in_words_survives_json_and_matches_no_transaction() -> None:
    assert describe(THREE) == "a bill from Checking coming due, 3 day(s) before"
    assert describe(DepositRule(CHECKING, "Checking", payee="Fibre", due_days=0, judge=True)) == (
        "a bill from Checking to a payee containing “Fibre” coming due, on the day, and she decides whether to tell you")
    rule = DepositRule(CHECKING, "Checking", payee="Fibre", due_days=2)
    assert from_json(to_json(rule)) == rule and "due_days" not in to_json(DepositRule(CHECKING, "Checking", 1))
    assert not matches(THREE, Transaction("t", TODAY, CHECKING, 100, True, ("Acme",), "in"), TODAY)
    due = Landed(500, TODAY, "Checking", "Internet", "out", due_in=0, autopay=True)
    assert landed_from_json(landed_to_json(due)) == due and "due_in" not in landed_to_json(Landed(1, TODAY, "C", None))
    with pytest.raises(ValueError):
        DepositRule(CHECKING, "Checking", min_cents=5, due_days=1)
    with pytest.raises(ValueError):
        DepositRule(CHECKING, "Checking", below_cents=5, due_days=1)
    with pytest.raises(ValueError):
        DepositRule(CHECKING, "Checking", due_days=-1)
    with pytest.raises(ValueError):
        from_json({**to_json(THREE), "due_days": "3"})
    with pytest.raises(ValueError):
        landed_from_json({**landed_to_json(due), "autopay": "yes"})


def test_the_tool_arms_a_bill_rule_by_fields(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            tools = AnsweringTools(h.home, h.alana, private=True)
            args = {"for": "Alana", "account_id": CHECKING, "account": "Checking", "bill_due_days": 3, "what": BRIEF}
            made = await tools.call(ToolCall("c1", specs.ON_MONEY, args))
            assert not made.is_error
            assert json.loads(made.content)["when"] == "a bill from Checking coming due, 3 day(s) before"
            (armed,) = await h.deposits.armed()
            assert armed.rule == THREE
            for n, bad in enumerate(({"direction": "out"}, {"balance_below": 5}, {"min_amount": 5},
                                     {"bill_due_days": "3"}, {"bill_due_days": -1},
                                     {"bill_due_days": CONFIG.max_due_days + 1}, {"bill_due_days": True},
                                     {"bill_due_days": None})):
                got = await tools.call(ToolCall(f"b{n}", specs.ON_MONEY, {k: v for k, v in {**args, **bad}.items()
                                                                          if v is not None}))
                assert got.is_error, bad
            assert len(await h.deposits.armed()) == 1

    run(go())


def test_the_longest_lead_stays_under_the_wakes_keeping() -> None:
    assert CONFIG.max_due_days + 1 < KEEP_DAYS


def test_old_rows_read_as_not_bills() -> None:
    old = {"account_id": CHECKING, "account_name": "Checking", "min_cents": 5, "payee": None, "payee_match": "contains"}
    assert from_json(old).due_days is None
    assert date.fromisoformat(on(0)) == TODAY
