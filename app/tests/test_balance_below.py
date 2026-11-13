"""A money rule on a balance falling below (`DepositRule.below_cents`): the deposit sense reads the household's accounts
while such a rule is armed and fires one reminder per fall, again only after the balance has recovered; a second holder
or a retry stores nothing twice; no ledger, no fire. Time is the `now` each poll is handed."""

import asyncio
import json
import re
from datetime import timedelta

import pytest
from ashley import logs
from ashley.channels.wake.reminder_turn import said
from ashley.inference.model import ToolCall
from ashley.criteria.record import Transaction
from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import DepositRule, Landed, describe, from_json, landed_from_json, landed_to_json, matches, to_json
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.db.pool import PoolDatabase
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from deposit_support import NOW, AnsweringTools, DepositSure, House, deposit, house
from money_support import CHECKING, account, page
from test_reminder_look import ALANA

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

LOW = DepositRule(CHECKING, "Checking", below_cents=20_000)
BRIEF = "Checking is running low: move some over from savings."


def balance(h: House, dollars: str) -> None:
    h.sure.answers["/api/v1/accounts"] = {"accounts": [account(CHECKING, "Checking", dollars),
                                                       account("a2", "Visa", "$5.00", "liability")],
                                          "pagination": page(2)}


async def fired(h: House) -> list[Reminder]:
    return [d.wake for d in await h.wakes.due(50) if isinstance(d.wake, Reminder)]


def test_it_fires_on_falling_below_not_again_while_below_and_again_after_recovering(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(LOW, BRIEF)
            steps = [("$1,000.00", 0), ("$150.00", 1), ("$90.00", 1), ("$150.00", 1), ("$200.00", 1), ("$199.99", 2),
                     ("$500.00", 2), ("-$5.00", 3)]
            for n, (dollars, want) in enumerate(steps):
                balance(h, dollars)
                await deposit_sense.poll(NOW + timedelta(minutes=5 * n))
                assert len(await fired(h)) == want, (n, dollars)

    run(go())


def test_the_fired_reminder_is_the_armed_ones_and_carries_the_balance_and_threshold(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(LOW, BRIEF)
            balance(h, "-$12.34")
            await deposit_sense.poll(NOW)
            (reminder,) = await fired(h)
            assert (reminder.person_id, reminder.brief) == (h.alana, BRIEF)
            assert reminder.landed == Landed(-1234, NOW.date(), "Checking", None, below_cents=20_000)
            text = said(reminder, ALANA, ALANA)
            assert "Checking is at -12.34, below 200.00, as read on 2026-11-03" in text
            assert "deposit that landed" not in text

    run(go())


def test_only_accounts_are_read_while_only_balance_rules_are_armed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(LOW)
            balance(h, "$1,000.00")
            await deposit_sense.poll(NOW)
            assert [p for p, _, _ in h.sure.seen] == ["/api/v1/accounts"]
            assert await h.deposits.read_through(h.home) is None

    run(go())


def test_accounts_are_not_read_while_only_transaction_rules_are_armed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(DepositRule(CHECKING, "Checking", 100_000, "Acme"))
            await deposit_sense.poll(NOW)
            assert {p for p, _, _ in h.sure.seen} == {"/api/v1/transactions"}

    run(go())


def test_a_balance_rule_and_a_transaction_rule_are_judged_in_one_poll(db_url: str) -> None:
    async def go() -> None:
        sure = DepositSure(rows=[deposit("t1", "Payroll", 150_000, NOW.date(), merchant="Acme")])
        async with house(db_url, sure) as h:
            await h.arm(LOW)
            await h.arm(DepositRule(CHECKING, "Checking", 100_000, "Acme"))
            balance(h, "$10.00")
            await deposit_sense.poll(NOW)
            kinds = sorted(r.landed.below_cents is not None for r in await fired(h) if r.landed is not None)
            assert kinds == [False, True]

    run(go())


@pytest.mark.parametrize("answer", [
    {"accounts": [account("other", "Savings", "$1.00")], "pagination": page(1)},
    {"accounts": [{**account(CHECKING, "Checking", "$1.00"), "balance_cents": None}], "pagination": page(1)},
], ids=["account-not-listed", "no-balance"])
def test_an_account_the_read_cannot_judge_fires_nothing(db_url: str, answer: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(LOW)
            h.sure.answers["/api/v1/accounts"] = answer
            await deposit_sense.poll(NOW)
            assert await fired(h) == []

    run(go())


def test_nothing_fires_with_no_ledger_connected(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(LOW)
            balance(h, "$1.00")
            h.connections.held.clear()
            await deposit_sense.poll(NOW)
            assert await fired(h) == [] and h.sure.seen == []
            h.connections.connect(h.home)
            await deposit_sense.poll(NOW + timedelta(minutes=5))
            assert len(await fired(h)) == 1

    run(go())
    assert "deposits.unreadable" in capsys.readouterr().out


def test_a_new_holder_with_no_memory_stores_no_second_reminder_for_one_fall(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            armed = await h.arm(LOW)
            balance(h, "$10.00")
            await deposit_sense.poll(NOW)
            other = PoolDatabase(db_url, connect_timeout_s=5.0)
            await other.open()
            try:
                second = PostgresDeposits(other)
                low = Landed(1_000, NOW.date(), "Checking", None, below_cents=20_000)
                assert not await second.below(armed, low)
                await second.recovered(armed)
                got = await asyncio.gather(h.deposits.below(armed, low), second.below(armed, low))
                assert sorted(got) == [False, True]
            finally:
                await other.close()
            assert len(await fired(h)) == 2

    run(go())


def test_a_cancelled_rule_fires_nothing(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            armed = await h.arm(LOW)
            assert await h.wakes.cancel(h.home, h.alana, armed)
            assert not await h.deposits.below(armed, Landed(1, NOW.date(), "Checking", None, below_cents=20_000))
            assert await fired(h) == []

    run(go())


def test_the_poll_line_counts_balances_and_never_says_an_amount(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with house(db_url, DepositSure()) as h:
            await h.arm(LOW)
            balance(h, "$123.45")
            await deposit_sense.poll(NOW)

    run(go())
    out = "\n".join(line for line in re.sub(r"\b(ts|duration_ms)=\S+", "", capsys.readouterr().out).splitlines()
                    if "logger=ashley.senses.deposits" in line)
    assert "balances=1" in out and "fell=1" in out and "deposits.fell" in out
    assert not any(s in out for s in ("123", "12345", "Checking", "200", "20000"))


def test_the_rule_reads_in_words_survives_json_and_matches_no_transaction() -> None:
    assert describe(LOW) == "the balance of Checking falling below 200.00"
    assert from_json(to_json(LOW)) == LOW
    assert "below_cents" not in to_json(DepositRule(CHECKING, "Checking", 1))
    assert not matches(LOW, Transaction("t", NOW.date(), CHECKING, 100, True, ("Acme",), "in"), NOW.date())
    low = Landed(-5, NOW.date(), "Checking", None, below_cents=0)
    assert landed_from_json(landed_to_json(low)) == low
    with pytest.raises(ValueError):
        DepositRule(CHECKING, "Checking", 5, below_cents=0)
    with pytest.raises(ValueError):
        DepositRule(CHECKING, "Checking", payee="Acme", below_cents=0)
    with pytest.raises(ValueError):
        from_json({**to_json(LOW), "below_cents": "200"})


def test_the_tool_arms_a_balance_rule_by_fields(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            tools = AnsweringTools(h.home, h.alana, private=True)
            args = {"for": "Alana", "account_id": CHECKING, "account": "Checking", "balance_below": 200, "what": BRIEF}
            made = await tools.call(ToolCall("c1", specs.ON_MONEY, args))
            assert not made.is_error and json.loads(made.content)["when"] == "the balance of Checking falling below 200.00"
            (armed,) = await h.deposits.armed()
            assert armed.rule == LOW
            for n, bad in enumerate(({"direction": "out"}, {"min_amount": 5}, {"balance_below": "200"},
                                     {"balance_below": None})):
                got = await tools.call(ToolCall(f"b{n}", specs.ON_MONEY, {k: v for k, v in {**args, **bad}.items()
                                                                          if v is not None}))
                assert got.is_error, bad
            assert len(await h.deposits.armed()) == 1

    run(go())


def test_old_rows_read_as_transaction_rules() -> None:
    old = {"account_id": CHECKING, "account_name": "Checking", "min_cents": 5, "payee": None, "payee_match": "contains"}
    assert from_json(old).below_cents is None
