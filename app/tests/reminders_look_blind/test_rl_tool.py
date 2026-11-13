"""`remind_on_money`: a rule needs a payee or a minimum, neither is optional in the other's absence and neither is
guessed; the schema offers both without a union a provider adapter may not accept; the guidance sends her to ask the
person when no past deposit shows the payer."""

import json

import pytest
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools import reminder_specs as specs
from contract.conversations_support import run
from deposit_support import AnsweringTools, House, house
from money_support import CHECKING

FIELDS = {"for": "Alana", "direction": "in", "account_id": CHECKING, "account": "Checking", "what": "Your bonus landed: move it."}


def spec_of(names: tuple[str, ...] = ("Alana",)) -> ToolSpec:
    return specs.remind_on_money(names)


async def call(h: House, **fields: object) -> ToolResult:
    return await AnsweringTools(h.home, h.alana, private=True).call(ToolCall("c1", specs.ON_MONEY, {**FIELDS, **fields}))


def test_the_schema_offers_a_payee_and_a_minimum_and_requires_neither() -> None:
    schema = json.loads(json.dumps(spec_of().parameters))
    assert {"payee", "min_amount"} <= set(schema["properties"])
    assert "payee" not in schema["required"] and "min_amount" not in schema["required"]
    assert schema["properties"]["direction"]["enum"] == ["in", "out"] and "balance_below" in schema["properties"]


def test_the_schema_has_no_union_a_provider_adapter_may_refuse() -> None:
    schema = spec_of().parameters
    for key in ("anyOf", "oneOf", "allOf", "not", "if", "then", "else"):
        assert key not in schema


def test_it_is_a_tool_that_changes_something() -> None:
    assert spec_of().reads is False


def test_the_description_says_a_rule_needs_one_of_them() -> None:
    text = spec_of().description
    assert "payee" in text and "min_amount" in text


def test_the_guidance_tells_her_to_ask_the_person_rather_than_guess(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            got = await AnsweringTools(h.home, h.alana, private=True).catalogue()
            text = (got.instructions or "") + " ".join(s.description for s in got.specs if s.name == specs.ON_MONEY)
            lowered = text.lower()
            assert "ask" in lowered and "guess" in lowered
            assert "payer" in lowered or "payee" in lowered

    run(go())


@pytest.mark.parametrize("fields", [{}, {"payee": ""}, {"payee": "   "}, {"payee": None}])
def test_a_rule_with_neither_a_payee_nor_a_minimum_is_refused_and_arms_nothing(db_url: str, fields: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            got = await call(h, **{k: v for k, v in fields.items() if v is not None})
            assert got.is_error
            assert await h.deposits.armed() == ()

    run(go())


@pytest.mark.parametrize("fields", [{"payee": "Acme"}, {"min_amount": 250}, {"payee": "Acme", "min_amount": 250}])
def test_a_payee_or_a_minimum_or_both_arms_it(db_url: str, fields: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            got = await call(h, **fields)
            assert not got.is_error
            (armed,) = await h.deposits.armed()
            assert (armed.rule.payee, armed.rule.min_cents) == (fields.get("payee"), 25_000 if "min_amount" in fields else None)

    run(go())
