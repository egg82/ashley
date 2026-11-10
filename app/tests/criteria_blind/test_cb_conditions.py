"""`reminder_conditions`: her `conditions` argument becomes clauses, in cents, with data defaults, and what exceeds a limit
or is not a predicate is refused."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley.criteria.predicates import KINDS, Predicate, holds
from ashley.tools import reminder_conditions as C
from ashley.tools.bench_args import BadArguments
from criteria_blind_support import BASE, monthly, tx

LIMITS: dict[str, int] = json.loads((Path(__file__).parents[2] / "ashley" / "senses" / "deposits.json").read_text())


def one(**p: object) -> Predicate:
    ((got,),) = C.parse([[p]])
    return got


def test_the_schema_is_an_array_of_arrays_of_predicate_objects_over_the_closed_kinds() -> None:
    s: Any = C.schema()
    assert s["type"] == "array" and s["items"]["type"] == "array"
    item = s["items"]["items"]
    assert item["type"] == "object" and set(item["properties"]["kind"]["enum"]) == set(KINDS) and item["required"] == ["kind"]
    assert "not" in item["properties"]
    assert "maxItems" not in json.dumps(s)
    json.dumps(s)


def test_no_conditions_is_no_clauses() -> None:
    assert C.parse(None) == () and C.parse([]) == ()


def test_the_example_in_the_description_parses_to_three_alternatives() -> None:
    got = C.parse([[{"kind": "payee", "text": "KVR"}, {"kind": "amount_vs_usual", "above_pct": 20}],
                   [{"kind": "payee", "text": "KVR"}, {"kind": "day_vs_usual"}], [{"kind": "payee_new"}]])
    assert [[p.kind for p in c] for c in got] == [["payee", "amount_vs_usual"], ["payee", "day_vs_usual"], ["payee_new"]]


def test_amounts_are_given_in_the_accounts_currency_and_stored_in_cents() -> None:
    p = one(kind="amount", min_amount=1500.5, max_amount=2000)
    assert (p.min_cents, p.max_cents) == (150_050, 200_000)
    assert one(kind="amount", min_amount=0.1).min_cents == 10
    assert one(kind="amount", min_amount=19.99).min_cents == 1999
    assert one(kind="amount", max_amount=3).min_cents is None


def test_not_flips_and_is_off_by_default() -> None:
    assert one(kind="payee", text="x", **{"not": True}).negate is True
    assert one(kind="payee", text="x", **{"not": False}).negate is False
    assert one(kind="payee", text="x").negate is False


def test_what_she_leaves_out_takes_the_data_default() -> None:
    assert one(kind="day_vs_usual").days == LIMITS["default_days"]
    assert one(kind="day_vs_usual").tolerance_days == LIMITS["default_tolerance_days"]
    assert one(kind="payee_new").min_seen == LIMITS["default_min_seen"]
    assert one(kind="payee_new").days == LIMITS["default_days"]
    assert one(kind="amount_vs_usual", above_pct=10).days == LIMITS["default_days"]
    assert one(kind="payee_new", days=30, min_seen=5) == Predicate("payee_new", days=30, min_seen=5)
    assert one(kind="day_vs_usual", days=45, tolerance_days=7) == Predicate("day_vs_usual", days=45, tolerance_days=7)
    p = one(kind="amount_vs_usual", days=45, above_pct=30, below_pct=10)
    assert (p.days, p.above_pct, p.below_pct) == (45, 30, 10)


def test_a_payee_without_a_match_contains_and_with_exact_is_exact() -> None:
    assert holds(one(kind="payee", text="kvr"), tx(payer="KVR Payroll"), [])
    assert not holds(one(kind="payee", text="kvr", match="exact"), tx(payer="KVR Payroll"), [])
    assert holds(one(kind="payee", text="kvr payroll", match="exact"), tx(payer="KVR Payroll"), [])


def test_amount_vs_usual_needs_a_bound_and_a_bare_one_is_refused() -> None:
    with pytest.raises(BadArguments):
        one(kind="amount_vs_usual")
    p = one(kind="amount_vs_usual", above_pct=20)
    read = monthly(4)
    assert holds(p, tx("now", BASE, 1_000_000), read) and not holds(p, tx("now", BASE, 100_000), read)


def test_the_limits_are_enforced_at_their_edge() -> None:
    ok = [[{"kind": "payee_new"}]] * LIMITS["max_clauses"]
    assert len(C.parse(ok)) == LIMITS["max_clauses"]
    with pytest.raises(BadArguments):
        C.parse(ok + [[{"kind": "payee_new"}]])
    full = [[{"kind": "payee_new"}] * LIMITS["max_predicates"]]
    assert len(C.parse(full)[0]) == LIMITS["max_predicates"]
    with pytest.raises(BadArguments):
        C.parse([[{"kind": "payee_new"}] * (LIMITS["max_predicates"] + 1)])
    assert one(kind="day_vs_usual", tolerance_days=LIMITS["max_tolerance_days"]).tolerance_days == LIMITS["max_tolerance_days"]
    with pytest.raises(BadArguments):
        one(kind="day_vs_usual", tolerance_days=LIMITS["max_tolerance_days"] + 1)
    assert one(kind="payee_new", days=LIMITS["max_days"]).days == LIMITS["max_days"]
    with pytest.raises(BadArguments):
        one(kind="payee_new", days=LIMITS["max_days"] + 1)


NOT_CLAUSES: list[object] = [
    "KVR", {"kind": "payee"}, [{"kind": "payee", "text": "x"}], [[]], [[{}]], [["payee"]], [[{"kind": "sideways"}]],
    [[{"kind": "payee"}]], [[{"kind": "payee", "text": ""}]], [[{"kind": "payee", "text": "x", "match": "fuzzy"}]],
    [[{"kind": "amount"}]], [[{"kind": "amount", "min_amount": -5}]], [[{"kind": "amount", "min_amount": "lots"}]],
    [[{"kind": "day_of_month", "first_day": 0, "last_day": 5}]], [[{"kind": "day_of_month", "first_day": 1, "last_day": 32}]],
    [[{"kind": "day_vs_usual", "days": 0}]], [[{"kind": "payee_new", "min_seen": 0}]],
    [[{"kind": "amount_vs_usual", "below_pct": 100}]], [[{"kind": "amount_vs_usual", "above_pct": -1}]],
    [[{"kind": "payee_new", "text": "x"}]], [[{"kind": "payee", "text": "x", "min_seen": 2}]]]


@pytest.mark.parametrize("raw", NOT_CLAUSES)
def test_what_is_not_a_clause_of_predicates_is_refused(raw: object) -> None:
    with pytest.raises(BadArguments):
        C.parse(raw)


def test_parsed_predicates_judge_like_hand_built_ones() -> None:
    got = C.parse([[{"kind": "payee", "text": "KVR"}, {"kind": "amount_vs_usual", "above_pct": 20, "days": 365}]])
    assert got == ((Predicate("payee", text="KVR", match="contains"), Predicate("amount_vs_usual", days=365, above_pct=20)),)
    d = tx("now", BASE + timedelta(days=0), 400_000)
    assert all(holds(p, d, monthly(4)) for p in got[0])
