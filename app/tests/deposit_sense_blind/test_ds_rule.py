"""`ashley.senses.deposit_rule`: `matches` compares a rule's fields to a deposit's own and reads no prose; `describe`
words a rule from its fields; `to_json` and `from_json` round-trip and refuse what they did not make."""

from datetime import date

import pytest
from ashley.senses.deposit_rule import Deposit, DepositRule, PayeeMatch, describe, from_json, matches, to_json

SINCE = date(2026, 10, 20)
ACCT = "acct-uuid-zq"
NAME = "Everyday Checking"


def rule(min_cents: int | None = None, payee: str | None = None, match: PayeeMatch = "contains") -> DepositRule:
    return DepositRule(ACCT, NAME, min_cents, payee, match)


def deposit(cents: int = 50000, day: date = SINCE, account: str = ACCT, counts: bool = True,
            names: tuple[str, ...] = ("Acme Payroll", "ACH CREDIT")) -> Deposit:
    return Deposit("t1", day, account, cents, counts, names)


def test_a_deposit_into_the_account_matches_a_rule_with_only_a_minimum_it_reaches() -> None:
    assert matches(rule(min_cents=50000), deposit(cents=50000), SINCE)
    assert matches(rule(min_cents=50000), deposit(cents=50001), SINCE)
    assert not matches(rule(min_cents=50000), deposit(cents=49999), SINCE)


def test_a_rule_with_only_a_payee_has_no_minimum() -> None:
    assert matches(rule(payee="acme"), deposit(cents=1), SINCE)


def test_the_account_must_be_the_rules_by_id_not_by_name() -> None:
    assert not matches(rule(min_cents=1), deposit(account="another-uuid"), SINCE)
    assert not matches(rule(min_cents=1), deposit(account=NAME), SINCE)


def test_a_deposit_matches_only_from_the_day_the_rule_was_set() -> None:
    assert matches(rule(min_cents=1), deposit(day=date(2026, 10, 20)), SINCE)
    assert matches(rule(min_cents=1), deposit(day=date(2026, 12, 1)), SINCE)
    assert not matches(rule(min_cents=1), deposit(day=date(2026, 10, 19)), SINCE)


def test_a_transaction_sure_does_not_count_never_matches() -> None:
    assert not matches(rule(min_cents=1), deposit(counts=False), SINCE)
    assert not matches(rule(payee="acme"), deposit(counts=False), SINCE)


@pytest.mark.parametrize("name,expected", [
    ("Acme Payroll", True), ("acme payroll", True), ("ACME PAYROLL", True),
    ("Acme Payroll Inc", False), ("Acme", False), ("Payroll", False), ("ACH", False),
])
def test_an_exact_payee_equals_a_name_whatever_the_case(name: str, expected: bool) -> None:
    assert matches(rule(payee=name, match="exact"), deposit(), SINCE) is expected


@pytest.mark.parametrize("name,expected", [
    ("Acme Payroll", True), ("payroll", True), ("ACME", True), ("me pay", True), ("Acme Payroll Inc", False),
    ("Globex", False),
])
def test_a_contains_payee_is_inside_a_name_whatever_the_case(name: str, expected: bool) -> None:
    assert matches(rule(payee=name, match="contains"), deposit(), SINCE) is expected


def test_a_payee_is_read_against_the_merchant_and_against_the_deposits_own_name() -> None:
    by_merchant = deposit(names=("Acme Payroll", "ACH CREDIT 4411"))
    by_own_name = deposit(names=("Acme Payroll", "ACH CREDIT 4411"))
    assert matches(rule(payee="Acme Payroll", match="exact"), by_merchant, SINCE)
    assert matches(rule(payee="ACH CREDIT 4411", match="exact"), by_own_name, SINCE)
    assert matches(rule(payee="Acme Payroll", match="exact"), deposit(names=("Acme Payroll",)), SINCE)
    assert not matches(rule(payee="Acme Payroll", match="exact"), deposit(names=()), SINCE)


def test_a_payee_and_a_minimum_both_have_to_hold() -> None:
    both = rule(min_cents=100000, payee="acme")
    assert matches(both, deposit(cents=100000), SINCE)
    assert not matches(both, deposit(cents=99999), SINCE)
    assert not matches(both, deposit(cents=100000, names=("Globex",)), SINCE)


def test_matching_reads_fields_and_not_words_a_payee_with_regex_characters_is_literal() -> None:
    assert not matches(rule(payee="Acme.*", match="contains"), deposit(), SINCE)
    assert matches(rule(payee="Acme.*", match="contains"), deposit(names=("Acme.* Co",)), SINCE)
    assert not matches(rule(payee="a|b", match="exact"), deposit(names=("a",)), SINCE)


def test_a_rule_that_waits_on_nothing_is_refused() -> None:
    with pytest.raises(ValueError):
        rule()


def test_a_rule_is_described_from_its_fields_for_a_screen() -> None:
    text = describe(rule(min_cents=123456, payee="Acme Payroll", match="exact"))
    assert NAME in text and "Acme Payroll" in text
    assert "1,234.56" in text or "1234.56" in text
    assert ACCT not in text


def test_the_description_follows_each_field() -> None:
    plain = describe(rule(min_cents=123456, payee="Acme", match="exact"))
    assert describe(rule(min_cents=123456, payee="Acme", match="contains")) != plain
    assert describe(rule(min_cents=654321, payee="Acme", match="exact")) != plain
    assert describe(rule(min_cents=123456, payee="Globex", match="exact")) != plain
    assert describe(DepositRule(ACCT, "Another Name", 123456, "Acme", "exact")) != plain
    only_payee = describe(rule(payee="Acme"))
    only_min = describe(rule(min_cents=123456))
    assert "Acme" in only_payee and "1,234.56" not in only_payee and "1234.56" not in only_payee
    assert ("1,234.56" in only_min or "1234.56" in only_min) and "Acme" not in only_min


@pytest.mark.parametrize("made", [
    rule(min_cents=5), rule(payee="Acme", match="exact"), rule(min_cents=100, payee="x", match="contains"),
])
def test_a_rule_round_trips_through_json(made: DepositRule) -> None:
    assert from_json(to_json(made)) == made
    assert to_json(made)["account_id"] == ACCT


@pytest.mark.parametrize("raw", [
    {}, {"account_id": ACCT}, {"account_id": 5, "account_name": NAME, "min_cents": 5},
    {"account_id": ACCT, "account_name": NAME, "min_cents": "5"},
    {"account_id": ACCT, "account_name": NAME, "payee": "x", "payee_match": "regex"},
    {"account_id": ACCT, "account_name": NAME, "min_cents": None, "payee": "x", "payee_match": "regex"},
    {"account_id": ACCT, "account_name": NAME, "min_cents": None, "payee": "x", "payee_match": None},
    {"account_id": ACCT, "account_name": NAME},
])
def test_from_json_refuses_what_to_json_does_not_make(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        from_json(raw)
