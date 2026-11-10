"""Gemini answers 400 to a call whose tools carry `maxItems` on nested arrays while its strict reply format is also sent,
so every chat call failed over to another route while `remind_on_money.conditions` had them. The bounds live in
`parse`, which refuses past them."""

import json

import pytest
from ashley.senses.deposit_config import CONFIG
from ashley.tools import reminder_conditions
from ashley.tools.bench_args import BadArguments


def test_the_conditions_schema_carries_no_max_items() -> None:
    text = json.dumps(reminder_conditions.schema())
    assert '"items"' in text
    assert '"maxItems"' not in text


def test_more_alternatives_than_the_limit_are_refused_by_parse() -> None:
    one = [{"kind": "payee", "text": "ACME"}]
    with pytest.raises(BadArguments):
        reminder_conditions.parse([one] * (CONFIG.criteria.max_clauses + 1))


def test_more_predicates_than_the_limit_are_refused_by_parse() -> None:
    with pytest.raises(BadArguments):
        reminder_conditions.parse([[{"kind": "payee", "text": "ACME"}] * (CONFIG.criteria.max_predicates + 1)])
