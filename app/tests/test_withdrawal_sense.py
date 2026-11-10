"""Rules that wait on money leaving (`direction` out): matched against transactions Sure classes expense and never a
transfer, split parent or excluded; the sense reads expenses only while an armed rule is `out`; the tool takes the
direction as a field; the fired reminder states, from data, that it left; rules and landed rows stored before the field
existed read as `in`."""

import json
import re
from dataclasses import replace
from datetime import date, timedelta

import pytest
from ashley import logs
from ashley.channels.wake.reminder_turn import said
from ashley.inference.model import ToolCall
from ashley.senses import deposit_sense, ledger_transactions
from ashley.sure.ledger import entry_from
from ashley.senses.deposit_rule import (Deposit, Direction, Landed, describe, from_json, landed_from_json,
                                        landed_to_json, matches, to_json)
from ashley.senses.wakes import Reminder
from ashley.sure import wire
from ashley.tools import reminder_specs as specs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from datetime import UTC, datetime
from deposit_support import NOW, AnsweringTools, DepositSure, deposit, house, rule
from money_support import CHECKING
from test_deposit_tools import FIELDS
from test_reminder_look import ALANA


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

DAY = date(2026, 11, 3)
OUT = replace(rule(), min_cents=50_000, payee=None, direction="out")


def spend(cents: int = 60_000, counts: bool = True, direction: Direction = "out") -> Deposit:
    return Deposit("t", DAY, CHECKING, cents, counts, ("Statewide Mutual", "ACH debit"), direction)


def test_an_out_rule_matches_only_money_going_out() -> None:
    assert matches(OUT, spend(), DAY)
    assert not matches(OUT, spend(direction="in"), DAY)
    assert not matches(rule(), spend(), DAY)
    assert not matches(OUT, spend(cents=49_999), DAY)
    assert not matches(OUT, spend(counts=False), DAY)


def test_it_reads_in_words_and_survives_json_and_an_old_row_is_in() -> None:
    insurance = replace(OUT, min_cents=None, payee="Statewide Mutual")
    assert describe(insurance) == "a withdrawal from Checking to a payee containing “Statewide Mutual”"
    assert from_json(to_json(insurance)) == insurance
    old = {k: v for k, v in to_json(rule()).items() if k != "direction"}
    assert from_json(old).direction == "in"
    with pytest.raises(ValueError):
        from_json({**to_json(rule()), "direction": "sideways"})


def test_landed_carries_direction_and_an_old_row_is_in() -> None:
    gone = Landed(60_000, DAY, "Checking", "Statewide Mutual", "out")
    assert landed_from_json(landed_to_json(gone)) == gone
    assert landed_from_json({k: v for k, v in landed_to_json(gone).items() if k != "direction"}).direction == "in"


def test_her_turn_says_it_left_from_the_field() -> None:
    out = said(Reminder(1, 2, 3, "check it", datetime.now(UTC), None, Landed(60_000, DAY, "Checking", "Statewide Mutual", "out")),
               ALANA, ALANA)
    assert "The withdrawal that left: 600.00 on 2026-11-03 out of Checking, to Statewide Mutual" in out
    assert "landed" not in out


def test_an_expense_fires_an_out_rule_once_and_states_its_direction(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH debit", 60_000, DAY, merchant="Statewide Mutual", classification="expense"),
                                 deposit("t2", "Payroll", 900_000, DAY, merchant="Acme")])
        async with house(db_url, sure) as h:
            await h.arm(OUT)
            await deposit_sense.poll(NOW)
            await deposit_sense.poll(NOW)
            (due,) = await h.wakes.due(10)
            assert isinstance(due.wake, Reminder) and due.wake.landed == Landed(60_000, DAY, "Checking", "Statewide Mutual", "out")
            assert {q["type"] for q in sure.polls()} == {"expense"}

    run(go())


@pytest.mark.parametrize("row", [
    deposit("t1", "Move", 60_000, DAY, merchant="Statewide Mutual", classification="expense", transfer=True),
    deposit("t2", "Bill", 60_000, DAY, merchant="Statewide Mutual", classification="expense", account_id="other"),
    deposit("t3", "Bill", 40_000, DAY, merchant="Statewide Mutual", classification="expense"),
    deposit("t4", "Bill", 60_000, date(2026, 10, 1), merchant="Statewide Mutual", classification="expense"),
], ids=["transfer", "other-account", "below-minimum", "before-it-was-set"])
def test_what_is_not_a_withdrawal_to_wait_for_fires_nothing(db_url: str, row: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure(rows=[row])) as h:
            await h.arm(OUT)
            await deposit_sense.poll(NOW)
            assert await h.wakes.due(10) == ()

    run(go())


def test_expenses_are_read_only_while_an_out_rule_is_armed_and_income_only_while_an_in_rule_is(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(rule())
            await deposit_sense.poll(NOW)
            assert {q["type"] for q in h.sure.polls()} == {"income"}
            h.sure.seen.clear()
            await h.arm(OUT)
            await deposit_sense.poll(NOW + timedelta(hours=1))
            assert {q["type"] for q in h.sure.polls()} == {"income", "expense"}

    run(go())


def test_the_poll_line_names_directions_never_what_was_paid(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "ACH debit", 60_000, DAY, merchant="Statewide Mutual", classification="expense")])
        async with house(db_url, sure) as h:
            await h.arm(OUT)
            await deposit_sense.poll(NOW)

    run(go())
    out = re.sub(r"\b(ts|duration_ms)=\S+", "", capsys.readouterr().out)
    assert "directions=out" in out and "Statewide Mutual" not in out and "600" not in out


def test_the_tool_arms_an_out_rule_by_fields_and_refuses_a_missing_direction(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            tools = AnsweringTools(h.home, h.alana, private=True)
            args = {**FIELDS, "direction": "out", "payee": None, "min_amount": 500}
            made = await tools.call(ToolCall("c1", specs.ON_MONEY, {k: v for k, v in args.items() if v is not None}))
            assert not made.is_error and json.loads(made.content)["when"] == "a withdrawal from Checking of at least 500.00"
            (armed,) = await h.deposits.armed()
            assert armed.rule.direction == "out"
            for bad in ({"direction": None}, {"direction": "sideways"}):
                again = {**FIELDS, **bad, "min_amount": 5}
                refused = await tools.call(ToolCall("c2", specs.ON_MONEY, {k: v for k, v in again.items() if v is not None}))
                assert refused.is_error
            assert len(await h.deposits.armed()) == 1

    run(go())


def test_a_row_counts_only_in_the_direction_it_was_read_for() -> None:
    row = wire.Transaction(id="t", date="2026-11-03", name="x", signed_amount_cents=-500, classification="expense")
    got_out, got_in = ledger_transactions.deposit_from(entry_from(row), "out"), ledger_transactions.deposit_from(entry_from(row), "in")
    assert got_out is not None and got_out.counts and got_out.cents == 500 and got_out.direction == "out"
    assert got_in is not None and not got_in.counts
