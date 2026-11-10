"""The conditions she composes a money rule from (`ashley.criteria.predicates`, `ashley.senses.deposit_rule`): each kind
decides from fields and the account's own history, the KVR-style composition fires on the unusual and not on the regular
paycheck or interest or an own-account transfer, and a rule with clauses survives JSON."""

from dataclasses import replace
from datetime import date

import pytest
from ashley.criteria import predicates
from ashley.criteria.predicates import KINDS, Predicate
from ashley.senses.deposit_rule import DepositRule, describe, from_json, landed, landed_from_json, landed_to_json, matches, to_json
from money_conditions_support import ACCOUNT, amount_off, composed, day_off, history, new_payer, payee, tx

NOV5 = date(2026, 11, 5)
SINCE = date(2026, 10, 1)


def rule(**fields: object) -> DepositRule:
    return replace(DepositRule(ACCOUNT, "Checking", clauses=composed()), **fields)


def fires(deposit_cents: int, name: str, day: date, counts: bool = True) -> bool:
    read = history()
    d = tx("new", name, deposit_cents, day, counts=counts)
    return matches(rule(), d, SINCE, [*read, d])
    read = history()
    return matches(rule(), d, SINCE, [*read, d])


def test_the_regular_paycheck_and_interest_do_not_fire() -> None:
    assert not fires(870_000, "KVR INC", NOV5)
    assert not fires(412, "INTEREST", date(2026, 11, 28))


def test_a_larger_or_smaller_paycheck_from_the_regular_payer_fires() -> None:
    assert fires(1_200_000, "KVR INC", NOV5)
    assert fires(400_000, "KVR INC", NOV5)


def test_a_paycheck_off_the_payers_usual_day_fires() -> None:
    assert fires(870_000, "KVR INC", date(2026, 11, 20))
    assert not fires(870_000, "KVR INC", date(2026, 11, 7))


def test_a_payer_the_account_has_not_seen_fires_at_any_amount() -> None:
    assert fires(632_000, "FPX PAYOUT", date(2026, 11, 25))
    assert fires(100, "FPX PAYOUT", date(2026, 11, 25))


def test_an_own_account_transfer_never_fires_even_from_a_new_payer() -> None:
    assert not fires(632_000, "FPX PAYOUT", date(2026, 11, 25), counts=False)


def test_a_payer_seen_once_is_new_until_min_seen_and_the_history_is_the_same_account_only() -> None:
    once = [tx("a", "ODD CO", 5_000, date(2026, 10, 1))]
    d = tx("b", "ODD CO", 5_000, date(2026, 11, 1))
    assert predicates.holds(new_payer(), d, [*once, d])
    other = [tx("c", "ODD CO", 5_000, date(2026, 10, 2), account="elsewhere")] * 3
    assert predicates.holds(new_payer(), d, [*once, *other, d])
    assert not predicates.holds(replace(new_payer(), min_seen=1), d, [*once, d])


def test_a_history_predicate_with_too_little_history_is_false_and_negate_flips_it() -> None:
    d = tx("b", "ODD CO", 5_000_000, date(2026, 11, 1))
    assert not predicates.holds(amount_off(), d, [d]) and not predicates.holds(day_off(), d, [d])
    assert predicates.holds(replace(amount_off(), negate=True), d, [d])


def test_the_fixed_kinds_each_decide_from_their_fields() -> None:
    d = tx("b", "Acme Payroll", 250_000, date(2026, 11, 30))
    cases = [(payee("acme"), True), (Predicate("payee", text="acme", match="exact"), False),
             (Predicate("amount", min_cents=200_000), True), (Predicate("amount", min_cents=300_000), False),
             (Predicate("amount", max_cents=300_000), True), (Predicate("day_of_month", first_day=28, last_day=31), True),
             (Predicate("day_of_month", first_day=1, last_day=5), False),
             (Predicate("day_of_month", first_day=28, last_day=3), True)]
    for p, want in cases:
        assert predicates.holds(p, d, [d]) is want, p
        assert predicates.holds(replace(p, negate=True), d, [d]) is not want, p


def test_a_malformed_predicate_is_refused() -> None:
    bad = [lambda: Predicate("payee", text="x"), lambda: Predicate("payee", text="x", match="contains", days=3),
           lambda: Predicate("amount"), lambda: Predicate("amount", min_cents=5, max_cents=1),
           lambda: Predicate("day_of_month", first_day=0, last_day=3),
           lambda: Predicate("amount_vs_usual", days=30), lambda: Predicate("amount_vs_usual", days=30, below_pct=100),
           lambda: Predicate("day_vs_usual", days=0, tolerance_days=1), lambda: Predicate("payee_new", days=5, min_seen=0),
           lambda: DepositRule(ACCOUNT, "C", clauses=((),)), lambda: DepositRule(ACCOUNT, "C")]
    for make in bad:
        with pytest.raises(ValueError):
            make()


def test_every_kind_has_its_fields_and_round_trips_and_reads_in_words() -> None:
    made = [payee("KVR"), Predicate("amount", min_cents=1, max_cents=9), Predicate("day_of_month", first_day=1, last_day=5),
            amount_off(), day_off(), new_payer()]
    assert {p.kind for p in made} == set(KINDS)
    for p in made:
        assert predicates.from_json(predicates.to_json(p)) == p and predicates.say(p)
    with pytest.raises(ValueError):
        predicates.from_json({**predicates.to_json(day_off()), "text": "x"})


def test_a_rule_with_clauses_and_judge_round_trips_and_older_rules_still_read() -> None:
    r = rule(judge=True)
    assert from_json(to_json(r)) == r
    old = {k: v for k, v in to_json(rule(payee="KVR")).items() if k not in ("clauses", "judge")}
    assert from_json(old).clauses == () and not from_json(old).judge
    assert ", when " in describe(r) and "decides" in describe(r)


def test_a_fired_deposit_carries_which_clause_held_and_the_payers_history() -> None:
    read = history()
    d = tx("new", "KVR INC", 1_200_000, NOV5)
    got = landed(rule(judge=True), d, [*read, d], 120)
    assert got.because == ("payee", "amount_vs_usual") and got.judged
    assert got.history is not None and (got.history.seen, got.history.low_cents, got.history.high_cents,
                                        got.history.every_days, got.history.last_day) == (3, 870_000, 870_000, 30, date(2026, 10, 5))
    assert landed_from_json(landed_to_json(got)) == got
    plain = landed(DepositRule(ACCOUNT, "Checking", min_cents=1), d)
    assert plain.history is None and not plain.judged and plain.because == ()


def test_a_transfer_from_the_same_name_is_not_part_of_the_payers_history() -> None:
    read = [*history(), tx("t", "KVR INC", 5_000_000, date(2026, 10, 20), counts=False)]
    d = tx("new", "KVR INC", 1_200_000, NOV5)
    assert predicates.holds(amount_off(), d, [*read, d]) and not predicates.holds(day_off(), d, [*read, d])
