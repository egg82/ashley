"""A rule composed from general predicates, end to end: the deposit sense reads the account's history from a fake Sure
and fires the composed rule on the FPX-style new payer and the off-day paycheck and not on the regular paycheck or
interest; the fire carries why and the payer's history; `remind_on_money` takes the composition as `conditions` with
defaults and limits from data, refuses a stray field, and offers only kinds the predicates know; a judged fire is not
promised and a quiet answer to it is recorded done with nothing pushed."""

import pytest
import json
from typing import Any
from datetime import date, timedelta

from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as push_config
from ashley.channels.push.subscriptions import Subscription
from ashley.channels.wake import reminder_turn, runner
from ashley.criteria.predicates import KINDS
from ashley.people.model import Person
from ashley.senses import deposit_sense
from ashley.senses.deposit_config import CONFIG
from ashley.senses.deposit_rule import DepositRule, Landed, landed_from_json
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from ashley.inference.model import ToolCall
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from deposit_support import NOW, AnsweringTools, DepositSure, deposit, house
from money_conditions_support import composed
from money_support import CHECKING
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions
from test_reminder_turn import SAYS, world


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")


def sure_with_history() -> DepositSure:
    rows = [deposit(f"p{d}", "KVR INC", 870_000, d, merchant="KVR INC") for d in (
        date(2026, 6, 5), date(2026, 7, 5), date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5), date(2026, 11, 3))]
    rows += [deposit("odd", "KVR INC", 870_000, date(2026, 10, 20), merchant="KVR INC"),
             deposit("iba", "FPX PAYOUT", 632_000, date(2026, 10, 28), merchant="FPX"),
             deposit("xfer", "TRANSFER FROM SAVINGS", 500_000, date(2026, 10, 29), transfer=True)]
    rows += [deposit(f"i{m}", "INTEREST", 412, date(2026, m, 28), merchant="Interest") for m in (6, 7, 8, 9, 10)]
    return DepositSure(rows=rows)


def landed_rows(url: str) -> list[Landed]:
    raw = scalar(url, "SELECT coalesce(json_agg(landed ORDER BY id), '[]') FROM wakes WHERE landed IS NOT NULL")
    return [landed_from_json(r) for r in raw]


def test_the_composed_rule_fires_on_the_new_payer_and_the_off_day_paycheck_only(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, sure_with_history()) as h:
            await h.arm(DepositRule(CHECKING, "Checking", clauses=composed()), at=NOW - timedelta(days=60))
            await deposit_sense.poll(NOW)
            got = landed_rows(db_url)
            assert sorted((g.payee, g.cents, g.because) for g in got) == [
                ("FPX", 632_000, ("payee_new",)), ("KVR INC", 870_000, ("payee", "day_vs_usual"))]
            iba = next(g for g in got if g.payee == "FPX")
            assert iba.history is not None and iba.history.seen == 0 and not iba.judged
            await deposit_sense.poll(NOW)
            assert len(landed_rows(db_url)) == 2
    run(go())


def test_a_rule_that_reads_no_history_reads_no_further_back(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, sure_with_history()) as h:
            await h.arm(DepositRule(CHECKING, "Checking", 100_000), at=NOW - timedelta(days=1))
            await deposit_sense.poll(NOW)
            assert min(q["start_date"] for q in h.sure.polls()) == "2026-11-02"
    run(go())


def test_the_tool_takes_conditions_with_defaults_and_refuses_strays_and_excess(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            tools = AnsweringTools(h.home, h.alana, private=True)
            base = {"for": "Alana", "direction": "in", "account_id": CHECKING, "account": "Checking", "what": "x"}

            async def arm(conditions: object, **more: object) -> tuple[bool, str]:
                made = await tools.call(ToolCall("c", specs.ON_MONEY, {**base, "conditions": conditions, **more}))
                return made.is_error, made.content

            err, body = await arm([[{"kind": "payee", "text": "KVR"}, {"kind": "amount_vs_usual", "above_pct": 25}],
                                   [{"kind": "payee_new"}]], judge=True)
            assert not err and "she decides" in json.loads(body)["when"]
            (armed,) = await h.deposits.armed()
            first, second = armed.rule.clauses
            assert first[0].match == "contains" and first[1].days == CONFIG.criteria.default_days
            assert second[0].min_seen == CONFIG.criteria.default_min_seen and armed.rule.judge
            bads: list[object] = [[[{"kind": "payee_new", "text": "x"}]], [[{"kind": "regular_income"}]], [[]],
                        [[{"kind": "payee_new", "days": CONFIG.criteria.max_days + 1}]],
                        [[{"kind": "day_vs_usual", "tolerance_days": CONFIG.criteria.max_tolerance_days + 1}]],
                        [[{"kind": "payee_new"}]] * (CONFIG.criteria.max_clauses + 1), "payee_new"]
            for bad in bads:
                assert (await arm(bad))[0], bad
            assert len(await h.deposits.armed()) == 1
    run(go())


def test_the_tool_offers_every_predicate_kind_and_the_guidance_names_only_real_ones() -> None:
    parameters: Any = specs.remind_on_money(["Alana"]).parameters
    assert parameters["properties"]["conditions"]["items"]["items"]["properties"]["kind"]["enum"] == list(KINDS)
    named = {w for w in specs.ON_MONEY_INSTRUCTIONS.replace(",", " ").replace(".", " ").split()
             if w.endswith("_vs_usual") or w == "payee_new"}
    assert named and named <= set(KINDS)


def test_a_judged_fire_is_not_promised_and_a_plain_one_is() -> None:
    alana = Person(1, 1, "Alana")
    judged = Reminder(1, 1, 1, "b", NOW, None, landed=Landed(100, date(2026, 11, 3), "C", "P", judged=True))
    plain = Reminder(1, 1, 1, "b", NOW, None, landed=Landed(100, date(2026, 11, 3), "C", "P"))
    assert not reminder_turn.inbound(1, judged, alana, alana).promised
    assert reminder_turn.inbound(1, plain, alana, alana).promised
    assert "`says`" in reminder_turn.said(judged, alana, alana)
    assert "`says`" not in reminder_turn.said(plain, alana, alana)


def test_a_judged_reminder_she_keeps_quiet_is_recorded_done_and_nothing_is_pushed(
        db_url: str, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            fired = await w.remind()
            scalar(db_url, "WITH u AS (UPDATE wakes SET landed = %s::jsonb WHERE id = %s RETURNING 1) "
                           "SELECT count(*) FROM u", (json.dumps({"cents": 1, "day": "2026-11-03", "account_name": "C",
                                                                   "payee": "P", "judged": True}), fired))
            sender = FakeSender()
            w.model.script = [SAYS]
            await runner.sweep()
            assert await push_reminders.deliver(sender, push_config()) == 1
            assert sender.sends == []
            assert scalar(db_url, "SELECT delivery FROM wakes WHERE id = %s", (fired,)) == "delivered"
    run(go())
