"""The rule and its readers, with no database: a rule matches only money going its own way, counted, in its account, at
least its minimum, with its payee; what was stored before `direction` existed reads as `in`; an unknown direction is
refused."""

from datetime import date

import pytest
from ashley.senses.deposit_rule import (DIRECTIONS, Deposit, DepositRule, Direction, Landed, describe, from_json,
                                        landed_from_json, landed_to_json, matches, to_json)
from ashley.senses.ledger_transactions import deposit_from
from ashley.sure.ledger import entry_from
from ashley.sure import wire
from money_support import CHECKING
from withdrawal_blind_support import DAY, rule_for

SINCE = date(2026, 11, 1)
BOTH: tuple[Direction, Direction] = ("in", "out")


def money(direction: Direction, cents: int = 60_000, counts: bool = True, names: tuple[str, ...] = ("Statewide Mutual",),
          day: date = DAY, account: str = CHECKING) -> Deposit:
    return Deposit("t", day, account, cents, counts, names, direction)


def test_the_directions_are_in_and_out() -> None:
    assert set(DIRECTIONS) == {"in", "out"}


@pytest.mark.parametrize("way", BOTH)
def test_a_rule_matches_its_own_direction_and_never_the_other(way: Direction) -> None:
    other: Direction = "out" if way == "in" else "in"
    assert matches(rule_for(way), money(way), SINCE)
    assert not matches(rule_for(way), money(other), SINCE)


@pytest.mark.parametrize("way", BOTH)
def test_a_row_that_does_not_count_matches_no_rule_either_way(way: Direction) -> None:
    assert matches(rule_for(way), money(way), SINCE)
    assert not matches(rule_for(way), money(way, counts=False), SINCE)


@pytest.mark.parametrize("way", BOTH)
def test_the_minimum_is_inclusive_to_the_cent(way: Direction) -> None:
    assert matches(rule_for(way, min_cents=50_000), money(way, cents=50_000), SINCE)
    assert matches(rule_for(way, min_cents=50_000), money(way, cents=50_001), SINCE)
    assert not matches(rule_for(way, min_cents=50_000), money(way, cents=49_999), SINCE)


@pytest.mark.parametrize("way", BOTH)
def test_another_account_and_a_day_before_the_rule_was_set_do_not_match(way: Direction) -> None:
    assert not matches(rule_for(way), money(way, account="elsewhere"), SINCE)
    assert not matches(rule_for(way), money(way, day=date(2026, 10, 31)), SINCE)
    assert matches(rule_for(way), money(way, day=SINCE), SINCE)


@pytest.mark.parametrize("way", BOTH)
@pytest.mark.parametrize("how,wanted,names,hit", [
    ("contains", "allst", ("ALLSTATE Insurance",), True),
    ("contains", "Statewide Mutual", ("State Farm",), False),
    ("exact", "allstate", ("ALLSTATE",), True),
    ("exact", "Statewide Mutual", ("Statewide Mutual Insurance",), False),
    ("exact", "Statewide Mutual", ("ACH debit", "Statewide Mutual"), True),
    ("contains", "Statewide Mutual", (), False),
])
def test_the_payee_is_exact_or_contained_without_regard_to_case(way: Direction, how: str, wanted: str,
                                                                names: tuple[str, ...], hit: bool) -> None:
    payee_rule = DepositRule(CHECKING, "Checking", None, wanted, "exact" if how == "exact" else "contains", way)
    assert matches(payee_rule, money(way, names=names), SINCE) is hit


def test_it_reads_in_words_and_the_two_directions_read_differently() -> None:
    said_out, said_in = describe(rule_for("out", payee="Statewide Mutual")), describe(rule_for("in", payee="Statewide Mutual"))
    assert said_out != said_in
    assert "withdrawal" in said_out and "withdrawal" not in said_in
    assert "Checking" in said_out and "Statewide Mutual" in said_out


@pytest.mark.parametrize("way", BOTH)
def test_a_rule_survives_json_in_either_direction(way: Direction) -> None:
    kept = rule_for(way, min_cents=None, payee="Statewide Mutual", match="exact")
    assert from_json(to_json(kept)) == kept
    assert to_json(kept)["direction"] == way


def test_a_rule_stored_before_direction_existed_reads_as_in() -> None:
    old = {k: v for k, v in to_json(rule_for("in")).items() if k != "direction"}
    assert "direction" not in old
    assert from_json(old) == rule_for("in")
    assert from_json(old).direction == "in"


@pytest.mark.parametrize("bad", ["sideways", "", "OUT", 1, ["out"]])
def test_an_unknown_direction_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        from_json({**to_json(rule_for("out")), "direction": bad})


@pytest.mark.parametrize("way", BOTH)
def test_a_landed_row_round_trips_with_its_direction(way: Direction) -> None:
    landed = Landed(60_000, DAY, "Checking", "Statewide Mutual", way)
    assert landed_from_json(landed_to_json(landed)) == landed
    assert landed_to_json(landed)["direction"] == way


def test_a_landed_row_stored_before_direction_existed_reads_as_in() -> None:
    old = {k: v for k, v in landed_to_json(Landed(60_000, DAY, "Checking", "Statewide Mutual", "out")).items() if k != "direction"}
    assert landed_from_json(old) == Landed(60_000, DAY, "Checking", "Statewide Mutual", "in")


def test_an_unknown_landed_direction_is_refused() -> None:
    with pytest.raises(ValueError):
        landed_from_json({**landed_to_json(Landed(1, DAY, "Checking", None, "in")), "direction": "sideways"})


def test_the_defaults_are_in() -> None:
    assert DepositRule(CHECKING, "Checking", None, "Acme", "contains").direction == "in"
    assert Deposit("t", DAY, CHECKING, 1, True, ()).direction == "in"
    assert Landed(1, DAY, "Checking", None).direction == "in"


def sure_row(cents: int, kind: str, **flags: object) -> wire.Transaction:
    return wire.Transaction.model_validate({
        "id": "t", "date": "2026-11-03", "name": "x", "signed_amount_cents": cents, "classification": kind,
        "account": {"id": CHECKING, "name": "Checking"}, **flags})


@pytest.mark.parametrize("way,cents,kind,counts", [
    ("out", -500, "expense", True), ("out", 500, "income", False),
    ("in", 500, "income", True), ("in", -500, "expense", False),
])
def test_a_row_counts_only_in_the_direction_it_was_read_for(way: Direction, cents: int, kind: str, counts: bool) -> None:
    got = deposit_from(entry_from(sure_row(cents, kind)), way)
    assert got is not None and got.counts is counts and got.cents == 500 and got.direction == way


@pytest.mark.parametrize("way,cents,kind", [("out", -500, "expense"), ("in", 500, "income")])
@pytest.mark.parametrize("flags", [{"excluded": True}, {"split_parent": True}, {"transfer": {"id": "x"}}],
                         ids=["excluded", "split-parent", "transfer"])
def test_excluded_split_and_transfer_rows_never_count(way: Direction, cents: int, kind: str, flags: dict[str, object]) -> None:
    got = deposit_from(entry_from(sure_row(cents, kind, **flags)), way)
    assert got is None or not got.counts
    control = deposit_from(entry_from(sure_row(cents, kind)), way)
    assert control is not None and control.counts

