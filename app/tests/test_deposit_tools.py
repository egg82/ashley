"""`remind_on_money` (`ashley.tools.reminders`): offered where the reply reaches the speaker alone and the household has
connected Sure; its guidance sends her to her money tools for the account and payee; it arms a reminder whose rule is the
fields she gave, shown back in words; bad fields store nothing; no log line carries an argument."""

import json
from datetime import UTC, datetime

import pytest
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.deposit_rule import DepositRule
from ashley.tools import reminder_specs as specs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from deposit_support import BONUS, AnsweringTools, House, house
from money_support import CHECKING
from ashley import logs
from connection_legacy_support import remove_of

FIELDS = {"for": "Alana", "direction": "in", "account_id": CHECKING, "account": "Checking", "min_amount": 1500.5, "payee": "Acme",
          "payee_match": "contains", "what": "Your bonus landed: move it to joint savings."}


async def call(h: House, **fields: object) -> ToolResult:
    tools = AnsweringTools(h.home, h.alana, private=True)
    args = {**FIELDS, **fields}
    return await tools.call(ToolCall("c1", specs.ON_MONEY, {k: v for k, v in args.items() if v is not None}))


def test_it_is_offered_only_to_a_private_speaker_whose_household_has_sure(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            private = await AnsweringTools(h.home, h.alana, private=True).catalogue()
            assert specs.ON_MONEY in [s.name for s in private.specs]
            assert private.instructions is not None and "money_transactions" in private.instructions
            shared = await AnsweringTools(h.home, h.alana, private=False).catalogue()
            assert specs.ON_MONEY not in [s.name for s in shared.specs]
            await remove_of(h.connections, h.home, "sure")
            bare = await AnsweringTools(h.home, h.alana, private=True).catalogue()
            assert specs.ON_MONEY not in [s.name for s in bare.specs]
            refused = await call(h)
            assert refused.is_error and refused.content.startswith("not_connected")

    run(go())


def test_she_arms_one_by_fields_and_it_is_listed_in_words(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            made = await call(h)
            body = json.loads(made.content)
            assert not made.is_error and body["when"] == "a deposit into Checking of at least 1500.50 from a payee " \
                                                          "containing “Acme”"
            (armed,) = await h.deposits.armed()
            assert armed.id == body["id"] and armed.household_id == h.home
            assert armed.rule == DepositRule(CHECKING, "Checking", 150_050, "Acme", "contains")
            assert abs((armed.armed_at - datetime.now(UTC)).total_seconds()) < 60
            (listed,) = await h.wakes.reminders(h.home, h.alana)
            assert listed.deposit == armed.rule and listed.state == "scheduled"
            assert await h.wakes.due(10) == ()

    run(go())


@pytest.mark.parametrize("bad", [
    {"account_id": None}, {"account": ""}, {"min_amount": None, "payee": None}, {"min_amount": -5},
    {"min_amount": True}, {"payee_match": "regex"}, {"for": "Nobody"}, {"what": ""}, {"extra": 1},
])
def test_bad_fields_arm_nothing(db_url: str, bad: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            got = await call(h, **bad)
            assert got.is_error and await h.deposits.armed() == ()

    run(go())


def test_no_log_line_carries_an_argument(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def go() -> None:
        async with house(db_url) as h:
            await call(h)

    run(go())
    out = capsys.readouterr().out
    assert "event=tools.call" in out
    for secret in ("Acme", "1500", "Checking", CHECKING, "bonus", BONUS):
        assert secret not in out
