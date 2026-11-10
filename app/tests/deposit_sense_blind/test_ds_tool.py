"""`remind_on_money` on `ReminderTools`: offered only when the turn is private and the household has Sure connected;
it arms a reminder from fields and refuses what it cannot make a rule of; nothing it is given reaches a log."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import logs
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.deposit_rule import DepositRule
from contract.conversations_support import run
from deposit_support import AnsweringTools
from ds_support import BONUS, BRIEF, CHECKING, NAMES, Folks, home

TOOL = "remind_on_money"


async def offered(f: Folks, house: int | None = None, who: int | None = None, private: bool = True) -> list[str]:
    tools = AnsweringTools(f.house if house is None else house, f.alana if who is None else who, private=private)
    return [s.name for s in (await tools.catalogue()).specs]


async def call(f: Folks, args: dict[str, object], private: bool = True, who: int | None = None) -> ToolResult:
    return await AnsweringTools(f.house, f.alana if who is None else who, private=private).call(ToolCall("c1", TOOL, args))


def good(**more: object) -> dict[str, object]:
    return {"for": "Alana", "direction": "in", "account_id": CHECKING, "account": NAMES[CHECKING], "what": BRIEF, **more}


def test_it_is_offered_in_a_private_turn_where_sure_is_connected(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            names = await offered(f)
            assert TOOL in names and "remind" in names

    run(go())


def test_it_is_not_offered_where_sure_is_not_connected(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url, with_sure=False) as f:
            names = await offered(f)
            assert TOOL not in names and "remind" in names

    run(go())


def test_a_household_with_only_home_assistant_connected_is_not_offered_it(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url, with_sure=False) as f:
            f.connections.connect(f.house, "https://ha.test", kind="home_assistant")
            assert TOOL not in await offered(f)
            f.connections.connect(f.house, "https://money.test", kind="sure")
            assert TOOL in await offered(f)

    run(go())


def test_a_call_where_sure_is_not_connected_is_an_error_and_arms_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url, with_sure=False) as f:
            assert (await call(f, good(min_amount=100))).is_error
            assert await f.armed() == ()

    run(go())


def test_it_is_not_offered_in_a_turn_that_is_not_private(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            assert TOOL not in await offered(f, private=False)
            assert TOOL in await offered(f, private=True)

    run(go())


def test_another_households_sure_does_not_offer_it_here(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url, with_sure=False) as f:
            house2, who2 = f.add_house("two", "https://two.test")
            assert TOOL not in await offered(f)
            assert TOOL in await offered(f, house=house2, who=who2)

    run(go())


def test_a_call_in_a_turn_that_is_not_private_arms_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            got = await call(f, good(min_amount=100), private=False)
            assert got.is_error
            assert await f.armed() == ()

    run(go())


def test_a_call_arms_a_reminder_on_the_rule_its_fields_make(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            before = datetime.now(UTC)
            got = await call(f, good(**{"for": "Sam", "min_amount": 1500.5, "payee": BONUS, "payee_match": "exact"}))
            assert not got.is_error
            (a,) = await f.armed()
            assert a.rule == DepositRule(CHECKING, NAMES[CHECKING], 150050, BONUS, "exact")
            assert a.household_id == f.house
            assert before - timedelta(seconds=5) <= a.armed_at <= datetime.now(UTC) + timedelta(seconds=5)
            (listed,) = [s for s in await f.wakes.reminders(f.house, f.sam) if s.deposit is not None]
            assert (listed.id, listed.reminder.person_id, listed.reminder.made_by, listed.reminder.brief) == (
                a.id, f.sam, f.alana, BRIEF)
            assert str(a.id) in got.content

    run(go())


@pytest.mark.parametrize("amount,cents", [(1500, 150000), (19.99, 1999), (0.07, 7), (1500.5, 150050), (1.15, 115)])
def test_an_amount_becomes_whole_cents_without_float_error(db_url: str, amount: float, cents: int) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            assert not (await call(f, good(min_amount=amount))).is_error
            (a,) = await f.armed()
            assert a.rule.min_cents == cents

    run(go())


def test_a_payee_alone_is_enough_and_the_match_defaults_to_contains(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            assert not (await call(f, good(payee="Acme"))).is_error
            (a,) = await f.armed()
            assert (a.rule.min_cents, a.rule.payee, a.rule.payee_match) == (None, "Acme", "contains")

    run(go())


@pytest.mark.parametrize("bad", [
    {}, {"min_amount": 0}, {"min_amount": -5}, {"min_amount": "lots"}, {"min_amount": 10, "payee_match": "regex"},
    {"payee": "Acme", "payee_match": "starts"}, {"min_amount": 10, "for": "Nobody"}, {"min_amount": 10, "what": ""},
    {"min_amount": 10, "what": "x" * 501}, {"min_amount": 10, "account_id": ""}, {"min_amount": 10, "what": "a\x00b"},
])
def test_a_call_that_makes_no_rule_is_an_error_and_arms_nothing(db_url: str, bad: dict[str, object]) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            assert (await call(f, good(**bad))).is_error
            assert await f.armed() == ()

    run(go())


@pytest.mark.parametrize("missing", ["for", "account_id", "account", "what"])
def test_each_required_field_is_required(db_url: str, missing: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            args = good(min_amount=100)
            del args[missing]
            assert (await call(f, args)).is_error
            assert await f.armed() == ()

    run(go())


def test_the_spec_names_the_fields_the_rule_is_made_of(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as f:
            specs = (await AnsweringTools(f.house, f.alana, private=True).catalogue()).specs
            (spec,) = [s for s in specs if s.name == TOOL]
            params: Mapping[str, Any] = spec.parameters
            props = params["properties"]
            assert {"for", "account_id", "account", "min_amount", "payee", "payee_match", "what"} <= set(props)
            assert sorted(props["for"]["enum"]) == ["Alana", "Sam"]
            assert sorted(props["payee_match"]["enum"]) == ["contains", "exact"]
            assert {"for", "account_id", "what"} <= set(params["required"])

    run(go())


def test_nothing_it_is_given_reaches_a_log(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        async with home(db_url) as f:
            await call(f, good(min_amount=987654.32, payee=BONUS, **{"what": "PlantedWhat-zq"}))
            await call(f, good(min_amount=-1, payee=BONUS, **{"what": "PlantedWhat-zq"}))

    run(go())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "tools.call" in text
    for secret in ("PlantedWhat", "Planted-zq", "PlantedChecking", "987654", CHECKING):
        assert secret not in text, secret
