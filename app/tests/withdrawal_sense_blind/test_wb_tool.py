"""`remind_on_money`'s direction, the turn her reminder becomes, and what the poll and the tool log."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import logs
from ashley.channels.wake.reminder_turn import said
from ashley.inference.model import ToolCall
from ashley.people.model import Person
from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import Direction, Landed
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from contract.conversations_support import run
from deposit_support import NOW, AnsweringTools, DepositSure, house
from money_support import CHECKING
from test_deposit_tools import FIELDS
from withdrawal_blind_support import DAY, SECRET_ACCOUNT, SECRET_PAYEE, row, rule_for


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

ALANA = Person(3, 1, "Alana")


def args(**more: object) -> dict[str, object]:
    return {k: v for k, v in {**FIELDS, "payee": None, "min_amount": 500, **more}.items() if v is not None}


@pytest.mark.parametrize("way", ["in", "out"])
def test_the_tool_arms_the_rule_in_the_direction_it_is_given(db_url: str, way: Direction) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            made = await AnsweringTools(h.home, h.alana, private=True).call(ToolCall("c", specs.ON_MONEY, args(direction=way)))
            assert not made.is_error
            (armed,) = await h.deposits.armed()
            assert armed.rule.direction == way and armed.rule.min_cents == 50_000

    run(go())


@pytest.mark.parametrize("bad", [None, "sideways", "", "OUT", 1])
def test_a_missing_or_unknown_direction_is_refused_and_arms_nothing(db_url: str, bad: object) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            tools = AnsweringTools(h.home, h.alana, private=True)
            assert not (await tools.call(ToolCall("ok", specs.ON_MONEY, args(direction="out")))).is_error
            refused = await tools.call(ToolCall("c", specs.ON_MONEY, args(direction=bad)))
            assert refused.is_error
            assert len(await h.deposits.armed()) == 1

    run(go())


def test_the_spec_requires_a_direction_of_in_or_out(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            catalogue = await AnsweringTools(h.home, h.alana, private=True).catalogue()
            (spec,) = [s for s in catalogue.specs if s.name == specs.ON_MONEY]
            params: Mapping[str, Any] = spec.parameters
            assert "direction" in params["required"]
            assert sorted(params["properties"]["direction"]["enum"]) == ["in", "out"]
            assert catalogue.instructions is not None and specs.ON_MONEY_INSTRUCTIONS in catalogue.instructions

    run(go())


@pytest.mark.parametrize("way,left", [("out", True), ("in", False)])
def test_her_turn_says_a_withdrawal_only_for_out(way: Direction, left: bool) -> None:
    text = said(Reminder(1, 3, 3, "check it", datetime.now(UTC), None, Landed(60_000, DAY, "Checking", "Statewide Mutual", way)),
                ALANA, ALANA)
    assert "600.00" in text and "Statewide Mutual" in text and "Checking" in text
    assert ("withdrawal" in text.lower()) is left


def test_the_poll_names_directions_and_nothing_that_was_paid(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        rows = [row("t1", 123_457, "out", payee=SECRET_PAYEE), row("t2", 123_458, "in", payee=SECRET_PAYEE)]
        async with house(db_url, DepositSure(rows=rows)) as h:
            await h.arm(rule_for("out", 100, account_name=SECRET_ACCOUNT))
            await deposit_sense.poll(NOW)
            await h.arm(rule_for("in", 100, account_name=SECRET_ACCOUNT))
            await deposit_sense.poll(NOW + timedelta(hours=1))
            assert len(await h.wakes.due(10)) == 2

    run(go())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "deposits.poll" in text and "directions=" in text and "directions=out" in text
    for secret in (SECRET_PAYEE, SECRET_ACCOUNT, "123457", "123458", "1234.57", "1,234.57", "1234.58", "Sentinel", CHECKING):
        assert secret not in text, secret


def test_the_tool_logs_neither_the_amount_the_payee_nor_the_account(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        async with house(db_url) as h:
            tools = AnsweringTools(h.home, h.alana, private=True)
            await tools.call(ToolCall("c", specs.ON_MONEY, args(direction="out", payee=SECRET_PAYEE, min_amount=987654.32,
                                                                account=SECRET_ACCOUNT)))
            await tools.call(ToolCall("d", specs.ON_MONEY, args(direction="sideways", payee=SECRET_PAYEE)))

    run(go())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "tools.call" in text
    for secret in (SECRET_PAYEE, SECRET_ACCOUNT, "987654", "9876.54", "Sentinel", json.dumps(CHECKING)):
        assert secret not in text, secret
