"""`DepositRule` with clauses: OR of ANDs, the old fields still ANDed, what a match stores, the history it asks for,
and the JSON round trip including rows stored before clauses existed."""

import json
from datetime import date, timedelta

import pytest
from ashley.criteria.predicates import Predicate, history_of
from ashley.criteria.record import Transaction
from ashley.senses import deposit_rule as R
from ashley.senses.deposit_rule import DepositRule, landed, matches
from criteria_blind_support import (ACCOUNT, BASE, above, amount, monthly, new_payer, off_day, payee, predicates, ref_holds,
                                    rule, tx, window)
from hypothesis import given, settings
from hypothesis import strategies as st

SINCE = date(2026, 10, 1)


def test_the_conditions_alone_make_a_rule_but_an_empty_clause_or_nothing_does_not() -> None:
    assert rule((payee("KVR"),)).clauses == ((payee("KVR"),),)
    with pytest.raises(ValueError):
        DepositRule(ACCOUNT, "Checking")
    with pytest.raises(ValueError):
        rule(())
    with pytest.raises(ValueError):
        rule((payee("KVR"),), ())


def test_a_clause_holds_when_every_predicate_of_it_holds_and_the_rule_when_any_clause_does() -> None:
    both = rule((payee("KVR"), amount(lo=50_000)))
    assert matches(both, tx(cents=60_000), SINCE)
    assert not matches(both, tx(cents=40_000), SINCE)
    assert not matches(both, tx(cents=60_000, payer="Acme"), SINCE)
    either = rule((payee("KVR"), amount(lo=500_000)), (payee("Acme"),))
    assert matches(either, tx(cents=600_000), SINCE) and matches(either, tx(payer="Acme Corp", cents=5), SINCE)
    assert not matches(either, tx(cents=60_000), SINCE) and not matches(either, tx(payer="Zed", cents=600_000), SINCE)


def test_a_negated_predicate_in_a_clause_excludes() -> None:
    r = rule((amount(lo=1000), payee("Refund", negate=True)))
    assert matches(r, tx(payer="KVR"), SINCE) and not matches(r, tx(payer="Big Refund Co"), SINCE)


def test_the_minimum_and_the_payee_are_still_anded_with_the_conditions() -> None:
    r = rule((window(1, 31),), min_cents=50_000, payee="KVR")
    assert matches(r, tx(cents=60_000), SINCE)
    assert not matches(r, tx(cents=40_000), SINCE)
    assert not matches(r, tx(payer="Acme", cents=60_000), SINCE)


def test_a_rule_still_needs_the_account_the_day_the_direction_and_a_counted_transaction() -> None:
    r = rule((window(1, 31),))
    assert matches(r, tx(), SINCE)
    assert not matches(r, tx(account="other"), SINCE)
    assert not matches(r, tx(counts=False), SINCE)
    assert not matches(r, tx(direction="out"), SINCE)
    assert not matches(r, tx(day=SINCE - timedelta(days=1)), SINCE)
    assert matches(r, tx(day=SINCE), SINCE)


def test_a_history_clause_reads_the_transactions_it_is_given_and_is_false_without_them() -> None:
    r = rule((payee("KVR"), above(20)))
    big = tx("now", cents=500_000)
    assert matches(r, big, SINCE, monthly(4))
    assert not matches(r, big, SINCE) and not matches(r, big, SINCE, [])
    assert not matches(r, tx("now", cents=100_000), SINCE, monthly(4))


def test_the_alana_rule_catches_a_bonus_a_late_paycheck_and_a_new_payer_but_not_the_usual_paycheck() -> None:
    r = rule((payee("KVR"), above(20)), (payee("KVR"), off_day(3)), (new_payer(2),))
    history = monthly(4)
    usual = tx("now", BASE, 100_000)
    assert history[-1].day + timedelta(days=30) == BASE
    assert not matches(r, usual, SINCE, [*history, usual])
    bonus = tx("now", BASE, 400_000)
    assert matches(r, bonus, SINCE, [*history, bonus])
    late = tx("now", BASE + timedelta(days=8), 100_000)
    assert matches(r, late, SINCE, [*history, late])
    iba = tx("now", BASE, 250_000, payer="FPX Payout")
    assert matches(r, iba, SINCE, [*history, iba])


@settings(max_examples=150, deadline=None)
@given(st.lists(st.lists(predicates(("payee", "amount", "day_of_month")), min_size=1,
                         max_size=3), min_size=1, max_size=3),
       st.integers(1, 800_000), st.sampled_from(["KVR Payroll", "Acme", "kvr"]), st.integers(1, 28))
def test_clauses_are_or_of_and_against_a_reference(clauses: list[list[Predicate]], cents: int, payer: str, dom: int) -> None:
    d = tx(cents=cents, payer=payer, day=date(2026, 10, dom))
    r = rule(*(tuple(c) for c in clauses))
    expected = any(all(ref_holds(p, d, []) for p in c) for c in clauses)
    assert matches(r, d, SINCE) is expected


def test_the_first_clause_that_holds_is_why_it_matched() -> None:
    r = rule((payee("Acme"), amount(lo=1)), (payee("KVR"), amount(lo=1)), (amount(lo=1),))
    got = landed(r, tx(), [])
    assert got.because == ("payee", "amount")
    assert landed(rule((payee("Zed"),), (amount(lo=1),)), tx(), []).because == ("amount",)


def test_a_rule_without_conditions_lands_with_no_reason_no_history_and_unjudged() -> None:
    got = landed(DepositRule(ACCOUNT, "Checking", 500, "KVR"), tx(cents=60_000), monthly(3))
    assert (got.cents, got.day, got.account_name, got.payee, got.direction) == (60_000, BASE, "Checking", "KVR Payroll", "in")
    assert got.because == () and got.history is None and got.judged is False


def test_a_landed_names_the_first_name_or_none_and_the_direction() -> None:
    r = rule((amount(lo=1),))
    assert landed(r, tx(payer=None), []).payee is None
    d = Transaction("t", BASE, ACCOUNT, 5, True, ("Acme", "ACH 44"), "in")
    assert landed(r, d, []).payee == "Acme"
    out = rule((amount(lo=1),), direction="out")
    assert landed(out, tx(direction="out"), []).direction == "out"


def test_a_rule_that_reads_history_lands_with_the_payers_history_over_the_longest_lookback_it_asks() -> None:
    read = [*monthly(4), tx("far", BASE - timedelta(days=200), 50_000)]
    d = tx("now", cents=400_000)
    r = rule((payee("KVR"), above(20, days=100)), (new_payer(2, days=10),))
    got = landed(r, d, read)
    assert got.history == history_of(d, read, 100) and got.history is not None and got.history.seen == 3
    assert landed(rule((above(20, days=250),)), d, read).history == history_of(d, read, 250)
    assert landed(rule((payee("KVR"),)), d, read).history is None


def test_a_judged_rule_lands_judged_with_history_over_at_least_the_judged_days() -> None:
    read = [*monthly(4), tx("far", BASE - timedelta(days=200), 50_000)]
    d = tx("now", cents=400_000)
    got = landed(rule((payee("KVR"),), judge=True), d, read, judged_days=250)
    assert got.judged is True and got.history == history_of(d, read, 250)
    longer = landed(rule((above(20, days=300),), judge=True), d, read, judged_days=40)
    assert longer.history == history_of(d, read, 300)
    assert landed(rule((payee("KVR"),)), d, read, judged_days=250).judged is False
    assert landed(rule((payee("KVR"),)), d, read, judged_days=250).history is None


def test_history_days_is_the_longest_a_history_predicate_asks_or_the_judged_days() -> None:
    assert rule((payee("KVR"),)).history_days(120) is None
    assert rule((payee("KVR"), amount(lo=1))).history_days(120) is None
    assert rule((payee("KVR"), above(20, days=40)), (new_payer(2, days=90), off_day(3, days=60))).history_days(30) == 90
    assert rule((above(20, days=40),)).history_days(500) == 40
    assert rule((payee("KVR"),), judge=True).history_days(120) == 120
    assert rule((above(20, days=200),), judge=True).history_days(120) == 200
    assert rule((above(20, days=40),), judge=True).history_days(120) == 120
    assert DepositRule(ACCOUNT, "Checking", 5, judge=True).history_days(77) == 77
    assert DepositRule(ACCOUNT, "Checking", 5).history_days(77) is None


def test_the_alana_rule_survives_json() -> None:
    r = rule((payee("KVR"), above(20)), (payee("KVR"), off_day(3)), (new_payer(2),), judge=True, direction="in",
             min_cents=1000, payee="KVR", payee_match="exact")
    raw = R.to_json(r)
    assert json.loads(json.dumps(raw)) == raw
    assert R.from_json(raw) == r and R.from_json(json.loads(json.dumps(raw))) == r


@settings(max_examples=100, deadline=None)
@given(st.lists(st.lists(predicates(), min_size=1, max_size=3), min_size=0, max_size=3), st.booleans(),
       st.sampled_from(["in", "out"]))
def test_any_rule_round_trips_through_json(clauses: list[list[Predicate]], judge: bool, way: R.Direction) -> None:
    r = DepositRule(ACCOUNT, "Checking", 100, None, "contains", way, tuple(tuple(c) for c in clauses), judge)
    assert R.from_json(json.loads(json.dumps(R.to_json(r)))) == r


def test_a_rule_stored_before_conditions_parses_and_behaves_as_it_did() -> None:
    old = {"account_id": ACCOUNT, "account_name": "Checking", "min_cents": 50_000, "payee": "KVR",
           "payee_match": "contains"}
    r = R.from_json(old)
    assert r == DepositRule(ACCOUNT, "Checking", 50_000, "KVR", "contains") and r.clauses == () and r.judge is False
    assert r.direction == "in"
    assert matches(r, tx(cents=60_000), SINCE) and not matches(r, tx(cents=40_000), SINCE)
    assert not matches(r, tx(payer="Acme", cents=60_000), SINCE)
    assert landed(r, tx(cents=60_000), []).because == ()


def test_an_old_payee_only_or_minimum_only_row_parses() -> None:
    assert R.from_json({"account_id": ACCOUNT, "account_name": "C", "min_cents": None, "payee": "KVR",
                        "payee_match": "exact"}).payee_match == "exact"
    assert R.from_json({"account_id": ACCOUNT, "account_name": "C", "min_cents": 5, "payee": None,
                        "payee_match": "contains"}).min_cents == 5


DAMAGE: list[dict[str, object]] = [
    {"clauses": [[]]}, {"clauses": "x"}, {"clauses": [[{"kind": "nope"}]]}, {"clauses": [["payee"]]}, {"judge": "yes"},
    {"clauses": [[{"kind": "payee", "text": "x", "match": "contains", "min_cents": 3}]]}]


@pytest.mark.parametrize("damage", DAMAGE)
def test_from_json_refuses_damaged_conditions(damage: dict[str, object]) -> None:
    good = R.to_json(rule((payee("KVR"),)))
    with pytest.raises(ValueError):
        R.from_json({**good, **damage})


def test_landed_survives_json_with_its_reason_and_history() -> None:
    r = rule((payee("KVR"), above(20)), judge=True)
    got = landed(r, tx("now", cents=400_000), monthly(4), judged_days=120)
    assert got.because and got.history is not None
    raw = R.landed_to_json(got)
    assert R.landed_from_json(json.loads(json.dumps(raw))) == got


def test_a_landed_stored_before_direction_was_out_is_in_and_without_reason() -> None:
    got = R.landed_from_json({"cents": 5, "day": "2026-10-04", "account_name": "C", "payee": None})
    assert got.direction == "in" and got.because == () and got.history is None and got.judged is False


def test_describe_says_the_conditions_and_the_old_fields() -> None:
    plain = R.describe(DepositRule(ACCOUNT, "Checking", 500, "KVR"))
    r = rule((payee("Acme"), above(37)), (new_payer(9),), min_cents=500, payee="KVR")
    said = R.describe(r)
    assert "Acme" in said and "37" in said and "9" in said and "KVR" in said and "Checking" in said
    assert R.describe(rule((payee("Acme"),))) != R.describe(rule((payee("Zed"),)))
    assert said != plain


def test_a_deposit_exactly_at_the_minimum_matches_and_one_cent_under_does_not() -> None:
    r = DepositRule(ACCOUNT, "Checking", 50_000, "KVR")
    assert matches(r, tx(cents=50_000), SINCE) and not matches(r, tx(cents=49_999), SINCE)
    c = rule((payee("KVR"),), min_cents=50_000)
    assert matches(c, tx(cents=50_000), SINCE) and not matches(c, tx(cents=49_999), SINCE)
