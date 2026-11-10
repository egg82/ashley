"""The poll on a real database: a rule fires only on money going its own way; a transfer, split parent or excluded row
never fires either way; the minimum and payee bound it; Sure is asked for expenses only while an `out` rule is armed;
one transaction fires one reminder however many pollers read it."""

import asyncio
from datetime import date, timedelta

import pytest
from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import Direction
from deposit_support import NOW, DepositSure, house
from contract.conversations_support import run
from withdrawal_blind_support import row, rule_for, polled


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

BOTH: tuple[Direction, Direction] = ("in", "out")


@pytest.mark.parametrize("way", BOTH)
def test_a_rule_fires_on_its_own_direction_and_never_on_the_other(db_url: str, way: Direction) -> None:
    other: Direction = "out" if way == "in" else "in"
    rows = [row("mine", 60_000, way), row("theirs", 61_000, other)]
    got = polled(db_url, rows, rule_for(way))
    assert got.cents == [60_000] and got.directions == [way]


@pytest.mark.parametrize("way", BOTH)
@pytest.mark.parametrize("transfer,excluded,split", [(True, False, False), (False, True, False), (False, False, True)],
                         ids=["transfer", "excluded", "split-parent"])
def test_a_transfer_a_split_parent_and_an_excluded_row_never_fire(db_url: str, way: Direction, transfer: bool,
                                                                 excluded: bool, split: bool) -> None:
    rows = [row("bad", 70_000, way, transfer=transfer, excluded=excluded, split_parent=split), row("good", 60_000, way)]
    got = polled(db_url, rows, rule_for(way))
    assert got.cents == [60_000]


@pytest.mark.parametrize("way", BOTH)
@pytest.mark.parametrize("cents,fires", [(49_999, 0), (50_000, 1), (50_001, 1)])
def test_the_minimum_fires_at_it_and_not_a_cent_under(db_url: str, way: Direction, cents: int, fires: int) -> None:
    got = polled(db_url, [row("t", cents, way)], rule_for(way, min_cents=50_000))
    assert len(got.cents) == fires


@pytest.mark.parametrize("way", BOTH)
@pytest.mark.parametrize("how,wanted,merchant,hit", [
    ("contains", "allst", "ALLSTATE Insurance", True),
    ("contains", "Statewide Mutual", "State Farm", False),
    ("exact", "allstate", "ALLSTATE", True),
    ("exact", "Statewide Mutual", "Statewide Mutual Insurance", False),
])
def test_the_payee_is_exact_or_contained_without_regard_to_case(db_url: str, way: Direction, how: str, wanted: str,
                                                                merchant: str, hit: bool) -> None:
    payee_rule = rule_for(way, None, wanted, "exact" if how == "exact" else "contains")
    got = polled(db_url, [row("t", 60_000, way, payee=merchant)], payee_rule)
    assert len(got.cents) == (1 if hit else 0)


@pytest.mark.parametrize("way", BOTH)
def test_a_payee_is_read_from_the_transaction_name_when_sure_names_no_merchant(db_url: str, way: Direction) -> None:
    got = polled(db_url, [row("t", 60_000, way, payee=None, name="ALLSTATE POLICY 4411")],
                        rule_for(way, None, "allstate"))
    assert len(got.cents) == 1


def test_a_day_before_the_rule_was_set_does_not_fire(db_url: str) -> None:
    got = polled(db_url, [row("old", 60_000, "out", day=date(2026, 10, 1)), row("new", 61_000, "out")],
                        rule_for("out"))
    assert got.cents == [61_000]


def test_both_rules_armed_each_fires_on_its_own_row_only(db_url: str) -> None:
    rows = [row("spent", 60_000, "out"), row("paid", 90_000, "in")]
    got = polled(db_url, rows, rule_for("in"), rule_for("out"))
    assert sorted(zip(got.directions, got.cents)) == [("in", 90_000), ("out", 60_000)]
    assert got.types_read == ["expense", "income"]


def test_expenses_are_not_read_while_only_in_rules_are_armed(db_url: str) -> None:
    got = polled(db_url, [row("t", 60_000, "in"), row("s", 61_000, "out")], rule_for("in"))
    assert got.types_read == ["income"] and got.cents == [60_000]


def test_income_is_not_read_while_only_out_rules_are_armed(db_url: str) -> None:
    got = polled(db_url, [row("t", 60_000, "in"), row("s", 61_000, "out")], rule_for("out"))
    assert got.types_read == ["expense"] and got.cents == [61_000]


def test_nothing_is_read_while_no_rule_is_armed(db_url: str) -> None:
    got = polled(db_url, [row("s", 61_000, "out")])
    assert got.types_read == [] and got.cents == []


def test_expenses_are_not_read_once_the_only_out_rule_is_cancelled(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure(rows=[row("s", 61_000, "out")])) as h:
            await h.arm(rule_for("in"))
            gone = await h.arm(rule_for("out"))
            assert await h.wakes.cancel(h.home, h.alana, gone) is True
            await deposit_sense.poll(NOW)
            assert sorted({q["type"] for q in h.sure.polls()}) == ["income"]

    run(go())


def test_two_pollers_reading_one_transaction_fire_it_once(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url, DepositSure(rows=[row("s", 61_000, "out"), row("p", 90_000, "in")])) as h:
            await h.arm(rule_for("out"))
            await asyncio.gather(deposit_sense.poll(NOW), deposit_sense.poll(NOW))
            await deposit_sense.poll(NOW + timedelta(hours=1))
            assert len(await h.wakes.due(50)) == 1

    run(go())


def test_two_withdrawals_fire_twice_and_a_later_poll_adds_none(db_url: str) -> None:
    got = polled(db_url, [row("a", 60_000, "out"), row("b", 61_000, "out")], rule_for("out"), polls=4)
    assert sorted(got.cents) == [60_000, 61_000]

