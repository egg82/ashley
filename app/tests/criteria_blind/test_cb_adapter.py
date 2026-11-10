"""The Sure adapter: Sure's rows become backend-neutral records the predicates read, income and expense each by their own
direction, with what is not income or spending (a transfer, a split parent, an excluded row) not counted."""

from datetime import date, timedelta

import pytest
from ashley.criteria.record import Direction, Transaction
from ashley.senses import ledger_transactions
from ashley.sure.ledger import entry_from
from ashley.sure import wire
from contract.conversations_support import run
from deposit_support import DepositSure, deposit, house
from money_support import CHECKING


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

DAY = date(2026, 11, 3)


def read(url: str, rows: list[dict[str, object]], *directions: Direction, start: date = DAY - timedelta(days=10)
         ) -> list[Transaction]:
    out: list[list[Transaction]] = []

    async def go() -> None:
        async with house(url, DepositSure(rows=rows)) as h:
            got, through = await ledger_transactions.read(h.home, start, directions)
            assert through is None
            out.append(got)

    run(go())
    return out[0]


def test_an_income_row_is_a_neutral_record_of_its_fields(db_url: str) -> None:
    (got,) = read(db_url, [deposit("t1", "ACH CREDIT 4411", 123_456, DAY, merchant="Acme")], "in")
    assert got == Transaction("t1", DAY, CHECKING, 123_456, True, ("Acme", "ACH CREDIT 4411"), "in")


def test_an_expense_row_has_unsigned_cents_and_the_direction_out(db_url: str) -> None:
    (got,) = read(db_url, [deposit("t1", "Rent", 90_000, DAY, merchant="Landlord", classification="expense")], "out")
    assert got.cents == 90_000 and got.direction == "out" and got.names == ("Landlord", "Rent") and got.counts is True


def test_a_row_with_no_merchant_is_named_by_its_own_name_only(db_url: str) -> None:
    (got,) = read(db_url, [deposit("t1", "ACH CREDIT 4411", 5, DAY)], "in")
    assert got.names == ("ACH CREDIT 4411",)


def test_each_direction_asked_for_is_read_and_the_other_is_not(db_url: str) -> None:
    rows = [deposit("i", "Pay", 5, DAY, merchant="Acme"), deposit("o", "Rent", 7, DAY, merchant="Landlord", classification="expense")]
    assert [(t.id, t.direction) for t in read(db_url, rows, "in")] == [("i", "in")]
    assert [(t.id, t.direction) for t in read(db_url, rows, "out")] == [("o", "out")]
    assert sorted((t.id, t.direction) for t in read(db_url, rows, "in", "out")) == [("i", "in"), ("o", "out")]


def test_a_transfer_is_read_but_not_counted(db_url: str) -> None:
    rows = [deposit("t1", "To savings", 5, DAY, merchant="Savings", transfer=True), deposit("t2", "Pay", 5, DAY, merchant="Acme")]
    assert {t.id: t.counts for t in read(db_url, rows, "in")} == {"t1": False, "t2": True}


def test_rows_before_the_start_day_are_not_read(db_url: str) -> None:
    rows = [deposit("old", "Pay", 5, DAY - timedelta(days=20), merchant="Acme"), deposit("new", "Pay", 5, DAY, merchant="Acme")]
    assert [t.id for t in read(db_url, rows, "in")] == ["new"]


def test_the_account_is_the_rows_account(db_url: str) -> None:
    other = "5c4d3e2f-1a0b-4c9d-8e7f-6a5b4c3d2e1f"
    rows = [deposit("a", "Pay", 5, DAY, merchant="Acme"), deposit("b", "Pay", 5, DAY, merchant="Acme", account_id=other)]
    assert {t.id: t.account_id for t in read(db_url, rows, "in")} == {"a": CHECKING, "b": other}


def test_a_row_sure_marks_excluded_or_a_split_parent_is_read_but_not_counted(db_url: str) -> None:
    rows = [deposit("e", "Pay", 5, DAY, merchant="Acme"), deposit("s", "Pay", 5, DAY, merchant="Acme"),
            deposit("ok", "Pay", 5, DAY, merchant="Acme")]
    rows[0]["excluded"] = True
    rows[1]["split_parent"] = True
    assert {t.id: t.counts for t in read(db_url, rows, "in")} == {"e": False, "s": False, "ok": True}


@pytest.mark.parametrize("way,kind,counts", [("in", "income", True), ("in", "expense", False), ("out", "expense", True),
                                              ("out", "income", False)])
def test_a_row_counts_only_in_the_direction_its_classification_says(way: Direction, kind: str, counts: bool) -> None:
    row = wire.Transaction.model_validate(deposit("t1", "Pay", 5, DAY, merchant="Acme", classification=kind))
    got = ledger_transactions.deposit_from(entry_from(row), way)
    assert got is not None and got.counts is counts and got.direction == way and got.cents == 5


def test_a_row_with_no_amount_or_an_unreadable_date_is_not_a_record() -> None:
    row = deposit("t1", "Pay", 5, DAY, merchant="Acme")
    assert ledger_transactions.deposit_from(entry_from(wire.Transaction.model_validate({**row, "signed_amount_cents": None})), "in") is None
    assert ledger_transactions.deposit_from(entry_from(wire.Transaction.model_validate({**row, "date": "soon"})), "in") is None
    assert ledger_transactions.deposit_from(entry_from(wire.Transaction.model_validate({**row, "id": None})), "in") is None
