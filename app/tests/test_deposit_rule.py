"""A deposit rule is fields (`ashley.senses.deposit_rule`): matching compares them to a transaction's own, never reads
prose; a rule is refused without a minimum or a payee; it is shown in words built from its fields and survives JSON."""

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from ashley.senses.deposit_rule import Deposit, DepositRule, describe, from_json, matches, to_json

DAY = date(2026, 11, 3)


def deposit(**fields: Any) -> Deposit:
    return replace(Deposit("t", DAY, "a1", 250_000, True, ("Acme Corp Bonus", "ACH credit")), **fields)


def test_each_field_decides() -> None:
    rule = DepositRule("a1", "Checking", 100_000, "acme", "contains")
    assert matches(rule, deposit(), DAY)
    assert not matches(rule, deposit(account_id="a2"), DAY)
    assert not matches(rule, deposit(cents=99_999), DAY)
    assert matches(rule, deposit(cents=100_000), DAY)
    assert not matches(rule, deposit(names=("Other",)), DAY)
    assert matches(rule, deposit(names=("Other", "ACME")), DAY)
    assert not matches(rule, deposit(counts=False), DAY)
    assert not matches(rule, deposit(day=date(2026, 11, 2)), DAY)


def test_exact_is_the_whole_name_and_contains_is_part_of_it() -> None:
    assert not matches(DepositRule("a1", "C", None, "Acme", "exact"), deposit(), DAY)
    assert matches(DepositRule("a1", "C", None, " acme corp bonus ", "exact"), deposit(), DAY)


def test_a_rule_needs_a_minimum_or_a_payee_and_sane_fields() -> None:
    good = DepositRule("a1", "C", 5, "x")
    for bad in (dict(min_cents=None, payee=None), dict(min_cents=0), dict(payee="  "), dict(account_id=""),
                dict(payee_match="regex")):
        with pytest.raises(ValueError):
            replace(good, **bad)


def test_it_reads_in_words_and_round_trips_through_json() -> None:
    rule = DepositRule("a1", "Bluebird Checking", 150_050, "Acme", "contains")
    assert describe(rule) == "a deposit into Bluebird Checking of at least 1500.50 from a payee containing “Acme”"
    assert from_json(to_json(rule)) == rule
    with pytest.raises(ValueError):
        from_json({"account_id": "a1"})
