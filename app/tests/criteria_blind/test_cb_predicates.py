"""Predicates over a neutral record: each kind's meaning, `not`, the closed set of kinds and fields, the words and
the JSON round trip."""

import json
from dataclasses import replace
from typing import Any
from datetime import date, timedelta

import pytest
from ashley.criteria import predicates as P
from ashley.criteria.predicates import KINDS, Predicate, holds
from ashley.criteria.record import Transaction
from criteria_blind_support import (BASE, above, amount, below, monthly, new_payer, off_day, payee, predicates, ref_history, ref_holds, ref_off_cadence, ref_past,
                                    tx, window)
from hypothesis import given, settings
from hypothesis import strategies as st


def test_the_kinds_are_the_six_the_docs_name() -> None:
    assert set(KINDS) == {"payee", "amount", "day_of_month", "amount_vs_usual", "day_vs_usual", "payee_new"}
    assert set(P.FIELDS) == set(KINDS)


def test_a_field_another_kind_uses_or_an_unknown_kind_is_refused() -> None:
    bad: Any = "sideways"
    with pytest.raises(ValueError):
        Predicate("payee", text="KVR", match="contains", min_cents=5)
    with pytest.raises(ValueError):
        Predicate("amount", min_cents=5, text="x")
    with pytest.raises(ValueError):
        Predicate("payee_new", min_cents=1, days=5)
    with pytest.raises(ValueError):
        Predicate(kind=bad)


@pytest.mark.parametrize("name,text,match,holds_", [
    ("KVR Payroll", "KVR", "contains", True), ("KVR Payroll", "payroll", "contains", True),
    ("KVR Payroll", "Acme", "contains", False), ("KVR Payroll", "KVR", "exact", False),
    ("KVR Payroll", "kvr payroll", "exact", True), ("KVR Payroll", "KVR Payroll", "exact", True)])
def test_payee_matches_the_name_by_contains_or_exact_ignoring_case(name: str, text: str, match: P.PayeeMatch,
                                                                 holds_: bool) -> None:
    assert holds(payee(text, match), tx(payer=name), []) is holds_


def test_payee_looks_at_every_name_the_record_carries() -> None:
    d = Transaction("t", BASE, "a", 100, True, ("Acme Corp", "ACH CREDIT 4411"))
    assert holds(payee("acme"), d, []) and holds(payee("4411"), d, []) and not holds(payee("KVR"), d, [])


def test_a_record_with_no_name_has_no_payee() -> None:
    assert not holds(payee("KVR"), tx(payer=None), [])


def test_amount_is_inclusive_at_the_minimum_and_bounded_above() -> None:
    assert holds(amount(lo=100_000), tx(cents=100_000), [])
    assert not holds(amount(lo=100_000), tx(cents=99_999), [])
    assert holds(amount(hi=50_000), tx(cents=49_999), [])
    assert not holds(amount(hi=50_000), tx(cents=50_001), [])
    assert holds(amount(10, 1000), tx(cents=500), []) and not holds(amount(10, 1000), tx(cents=5), [])
    assert not holds(amount(10, 1000), tx(cents=5000), [])


@pytest.mark.parametrize("day,first,last,expected", [(3, 1, 5, True), (6, 1, 5, False), (1, 1, 5, True), (5, 1, 5, True),
                                                      (15, 15, 15, True), (14, 15, 15, False), (16, 15, 15, False)])
def test_day_of_month_is_the_window_of_the_dated_day(day: int, first: int, last: int, expected: bool) -> None:
    assert holds(window(first, last), tx(day=date(2026, 10, day)), []) is expected


def test_not_flips_every_non_history_kind() -> None:
    d = tx(cents=1500, day=date(2026, 10, 10))
    for p in (payee("KVR"), payee("zzz"), amount(1000), amount(5000), window(1, 5), window(8, 12)):
        flipped = replace(p, negate=True)
        assert holds(flipped, d, []) is (not holds(p, d, []))


def test_amount_vs_usual_is_above_the_largest_or_below_the_smallest_by_a_percent() -> None:
    read = [tx("a", BASE - timedelta(days=60), 100_000), tx("b", BASE - timedelta(days=30), 120_000)]
    assert holds(above(20), tx(cents=150_000), read)       # 25% over 120_000
    assert not holds(above(20), tx(cents=140_000), read)   # 16% over
    assert not holds(above(20), tx(cents=110_000), read)   # inside the range
    assert holds(below(20), tx(cents=70_000), read)        # 30% under 100_000
    assert not holds(below(20), tx(cents=90_000), read)    # 10% under
    assert not holds(below(20), tx(cents=110_000), read)


def test_amount_vs_usual_with_both_bounds_holds_on_either() -> None:
    both = Predicate("amount_vs_usual", days=120, above_pct=20, below_pct=20)
    read = [tx("a", BASE - timedelta(days=60), 100_000), tx("b", BASE - timedelta(days=30), 120_000)]
    assert holds(both, tx(cents=150_000), read) and holds(both, tx(cents=70_000), read)
    assert not holds(both, tx(cents=110_000), read)


def test_a_history_predicate_with_no_history_is_false() -> None:
    for p in (above(0), below(0), off_day(0)):
        assert not holds(p, tx(cents=999_999_999), [])
    assert holds(new_payer(2), tx(), [])


def test_day_vs_usual_needs_a_cadence_which_one_deposit_does_not_give() -> None:
    assert not holds(off_day(0), tx(day=BASE), [tx("a", BASE - timedelta(days=11))])


def test_day_vs_usual_on_a_thirty_day_cadence_and_a_tolerance_of_three() -> None:
    read = monthly(4, 30, end=BASE - timedelta(days=30))   # the newest 30 days before the one under test... see below
    last = max(r.day for r in read)
    for off, expected in [(30, False), (33, False), (27, False), (34, True), (26, True), (60, False), (65, True)]:
        d = tx("now", last + timedelta(days=off))
        assert holds(off_day(3), d, read) is expected, off


def test_day_vs_usual_is_off_a_whole_cadence_so_the_day_after_a_deposit_is_off() -> None:
    read = monthly(4, 30)
    assert holds(off_day(1), tx("now", read[-1].day + timedelta(days=2)), read)


def test_day_vs_usual_measures_from_any_past_deposit_not_only_the_last() -> None:
    read = monthly(4, 30)
    d = tx("now", read[0].day + timedelta(days=90))      # 90 after the oldest, 60 after the next: a whole cadence from both
    assert not holds(off_day(1), d, read)


def test_the_cadence_is_the_median_gap() -> None:
    gaps = [7, 30, 30]       # the median is 30, the mean is not
    days = [BASE - timedelta(days=200)]
    for g in gaps:
        days.append(days[-1] + timedelta(days=g))
    days.append(days[-1] + timedelta(days=30))
    read = [tx(f"h{i}", x) for i, x in enumerate(days)]
    assert P.history_of(tx("now", days[-1] + timedelta(days=30)), read, 365).every_days == 30
    assert not holds(off_day(2), tx("now", days[-1] + timedelta(days=30)), read)
    assert holds(off_day(2), tx("now", days[-1] + timedelta(days=15)), read)


def test_payee_new_counts_the_payers_earlier_deposits_against_min_seen() -> None:
    for seen in range(0, 4):
        read = [tx(f"h{i}", BASE - timedelta(days=10 * (i + 1))) for i in range(seen)]
        for min_seen in (1, 2, 3):
            assert holds(new_payer(min_seen), tx(), read) is (seen < min_seen), (seen, min_seen)


def test_the_deposit_itself_in_the_read_is_not_its_own_history() -> None:
    d = tx("now", cents=500_000)
    read = [*monthly(4), d]
    assert holds(above(10), d, read) and not holds(new_payer(1), d, read)
    assert P.history_of(d, read, 365) == P.history_of(d, monthly(4), 365)


def test_other_payers_other_accounts_the_other_direction_and_transfers_are_not_the_payers_history() -> None:
    d = tx("now", cents=500_000)
    noise = [tx("a", BASE - timedelta(days=5), payer="Someone Else"), tx("b", BASE - timedelta(days=6), account="other"),
             tx("c", BASE - timedelta(days=7), direction="out"), tx("d", BASE - timedelta(days=8), counts=False)]
    assert P.history_of(d, noise, 120).seen == 0
    assert holds(new_payer(1), d, noise) and not holds(above(0), d, noise)


def test_only_the_lookback_window_and_days_up_to_the_deposit_are_history() -> None:
    d = tx("now", cents=500_000)
    read = [tx("old", BASE - timedelta(days=200)), tx("future", BASE + timedelta(days=3)),
            tx("in", BASE - timedelta(days=20))]
    assert P.history_of(d, read, 100).seen == 1
    assert P.history_of(d, read, 300).seen == 2
    assert P.history_of(d, read, 5).seen == 0


def test_history_reports_the_payers_pattern() -> None:
    read = [tx("a", BASE - timedelta(days=40), 90_000), tx("b", BASE - timedelta(days=10), 130_000)]
    h = P.history_of(tx("now"), read, 120)
    assert (h.seen, h.low_cents, h.high_cents, h.last_day) == (2, 90_000, 130_000, BASE - timedelta(days=10))
    assert P.history_of(tx("now"), [], 120) == P.History(0)


def test_not_flips_a_history_predicate_over_history_it_has() -> None:
    read = monthly(4)
    for p in (above(20), below(20), off_day(3), new_payer(2)):
        flipped = replace(p, negate=True)
        for cents in (60_000, 100_000, 300_000):
            d = tx("now", BASE, cents)
            assert holds(flipped, d, read) is (not holds(p, d, read))


@st.composite
def worlds(draw: st.DrawFn, kinds: tuple[str, ...] = ()) -> tuple[Predicate, Transaction, list[Transaction]]:
    n = draw(st.sampled_from([0, 1, 4]))
    offsets = sorted(draw(st.lists(st.integers(1, 200), min_size=n, max_size=n, unique=True)), reverse=True)
    same = [tx(f"h{i}", BASE - timedelta(days=o), draw(st.integers(1, 500_000))) for i, o in enumerate(offsets)]
    noise = [tx(f"n{i}", BASE - timedelta(days=draw(st.integers(1, 200))), draw(st.integers(1, 500_000)),
                payer=draw(st.sampled_from(["Other", None])), counts=draw(st.booleans())) for i in range(draw(st.integers(0, 2)))]
    d = tx("now", BASE, draw(st.integers(1, 800_000)))
    return draw(predicates(kinds)), d, [*same, *noise, d]


GROUPS: list[tuple[str, ...]] = [("payee", "amount", "day_of_month"), ("amount_vs_usual",), ("day_vs_usual",), ("payee_new",)]


@pytest.mark.parametrize("kinds", GROUPS, ids=lambda k: k[0])
@settings(max_examples=60, deadline=None)
@given(st.data())
def test_holds_agrees_with_the_reference_written_from_the_docs(kinds: tuple[str, ...], data: st.DataObject) -> None:
    p, d, read = data.draw(worlds(kinds))
    rows = read
    days = p.days or 120
    edge = [r for r in rows if r.id != d.id and abs((d.day - r.day).days - days) <= 1]
    if edge:
        return          # exactly at the lookback edge the docs do not say whether the day is in
    if p.kind == "day_vs_usual" and len(ref_past(d, rows, days)) not in (0, 1) and (
            len(ref_past(d, rows, days)) < 4 or len(ref_past(d, rows, days)) % 2):
        return          # the docs do not say how a median of an even count of gaps is rounded, nor the least history
    if p.kind == "day_vs_usual" and ref_past(d, rows, days):
        h = ref_history(d, rows, days)
        if h.every_days is not None and ref_off_cadence(d, ref_past(d, rows, days), h.every_days, p.tolerance_days or 0) != \
                ref_off_cadence(d, ref_past(d, rows, days), h.every_days, p.tolerance_days or 0, first=0):
            return      # the docs do not say whether the same day as a past deposit (no cadence at all) is on cadence
    if p.kind in ("amount_vs_usual",):
        high = max([r.cents for r in rows if r.id.startswith("h") and (d.day - r.day).days <= days] or [0])
        low = min([r.cents for r in rows if r.id.startswith("h") and (d.day - r.day).days <= days] or [0])
        for pct, ref in ((p.above_pct, high), (p.below_pct, low)):
            if pct is not None and ref and d.cents * 100 in (ref * (100 + pct), ref * (100 - pct)):
                return
    assert holds(p, d, rows) is ref_holds(p, d, rows)


@pytest.mark.parametrize("kinds", GROUPS, ids=lambda k: k[0])
@settings(max_examples=40, deadline=None)
@given(st.data())
def test_negate_is_the_exact_complement_of_the_same_predicate(kinds: tuple[str, ...], data: st.DataObject) -> None:
    p, d, read = data.draw(worlds(kinds))
    rows = read
    plain = replace(p, negate=False)
    flipped = replace(p, negate=True)
    assert holds(flipped, d, rows) is (not holds(plain, d, rows))


@settings(max_examples=100, deadline=None)
@given(predicates())
def test_a_predicate_survives_json_and_the_json_is_plain(p: Predicate) -> None:
    raw = P.to_json(p)
    assert json.loads(json.dumps(raw)) == raw
    assert P.from_json(raw) == p
    assert P.from_json(json.loads(json.dumps(raw))) == p


@given(predicates(), predicates())
def test_different_predicates_have_different_json(a: Predicate, b: Predicate) -> None:
    if a != b:
        assert P.to_json(a) != P.to_json(b)


@pytest.mark.parametrize("raw", [
    {}, {"kind": "nope"}, {"kind": "payee", "text": 5, "match": "contains"}, {"kind": "payee", "text": "x", "match": "fuzzy"},
    {"kind": "payee", "text": "x", "match": "contains", "min_cents": 5}, {"kind": "amount", "min_cents": "5"},
    {"kind": "payee_new", "days": "ten", "min_seen": 2}, {"kind": "payee", "text": "x", "match": "contains", "negate": "yes"}])
def test_from_json_refuses_what_to_json_does_not_make(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        P.from_json(raw)


def test_say_names_the_parameters_and_tells_a_negation_from_the_plain_predicate() -> None:
    assert "KVR" in P.say(payee("KVR")) and "Acme" in P.say(payee("Acme", "exact"))
    assert P.say(payee("KVR")) != P.say(payee("KVR", negate=True))
    assert P.say(payee("KVR", "exact")) != P.say(payee("KVR", "contains"))
    assert "10" in P.say(window(10, 20)) and "20" in P.say(window(10, 20))
    assert "25" in P.say(above(25)) and "40" in P.say(below(40))
    assert "9" in P.say(off_day(9)) and "7" in P.say(new_payer(7))
    assert "90" in P.say(above(25, days=90))
    assert len({P.say(p) for p in (above(25), below(25), off_day(3), new_payer(2), window(1, 5), amount(500))}) == 6


def test_a_deposit_exactly_at_the_percent_over_the_largest_is_not_over_it() -> None:
    read = [tx("a", BASE - timedelta(days=30), 100_000)]
    assert not holds(above(20), tx("now", cents=120_000), read)
    assert holds(above(20), tx("now", cents=120_001), read)


def test_a_deposit_exactly_at_the_percent_under_the_smallest_is_not_under_it() -> None:
    read = [tx("a", BASE - timedelta(days=30), 100_000)]
    assert not holds(below(20), tx("now", cents=80_000), read)
    assert holds(below(20), tx("now", cents=79_999), read)


def test_the_amount_maximum_is_inclusive_as_its_words_say_at_most() -> None:
    assert holds(amount(hi=50_000), tx(cents=50_000), [])
    assert "at most" in P.say(amount(hi=50_000))


def test_a_deposit_on_the_cadence_of_its_latest_neighbour_is_on_cadence_whatever_the_older_ones_say() -> None:
    gaps = [30, 30, 38]       # median 30; the newest deposit is exactly a cadence before the one under test
    days = [BASE - timedelta(days=30)]
    for g in reversed(gaps):
        days.insert(0, days[0] - timedelta(days=g))
    read = [tx(f"h{i}", x) for i, x in enumerate(days)]
    assert P.history_of(tx("now"), read, 365).every_days == 30
    assert not holds(off_day(3), tx("now"), read)
