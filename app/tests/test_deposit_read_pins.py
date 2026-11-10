"""What the deposit sense reads of a household's ledger, pinned before it moves behind the Ledger port: what is asked
for each direction, the pages read when there are more than `max_pages`, the day a cut read continues from, which
transactions become a record and what a record carries."""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date

import httpx2
import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.criteria.record import Direction, Transaction
from ashley.senses import ledger_transactions as reading
from ashley.sure.ledger import entry_from
from ashley.sure import wire
from ashley.ledger.model import LedgerFailed, NotConnected
from ashley.sure.client import Sure
from deposit_support import SAVINGS, DepositSure, deposit
from money_support import CHECKING, HeldConnections, page


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10
FAILED = LedgerFailed
UNRECOGNISED = "unrecognised"
DAY = date(2026, 10, 30)
SMALL = replace(reading.CONFIG, per_page=2, max_pages=2)


@pytest.fixture
def held() -> Iterator[HeldConnections]:
    found = HeldConnections()
    found.connect(HOME)
    services.register(Connections, found)
    yield found
    services.unregister(Connections)


@dataclass
class Fixed(DepositSure):
    """Answers every transactions request with `body`, whatever was asked."""

    body: object = None

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path != "/api/v1/transactions":
            return super().handle(request)
        self.seen.append((request.url.path, dict(request.url.params), request.headers.get("x-api-key")))
        return httpx2.Response(200, content=json.dumps(self.body).encode(), headers={"content-type": "application/json"})


def served(sure: DepositSure) -> DepositSure:
    services.register(Sure, sure.client())
    return sure


@pytest.fixture(autouse=True)
def cleanup(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(reading, "CONFIG", SMALL)
    yield
    services.unregister(Sure)


def read(start: date, *directions: Direction) -> tuple[list[Transaction], date | None]:
    return asyncio.run(reading.read(HOME, start, directions))


def rows(*days: int, classification: str = "income") -> list[dict[str, object]]:
    return [deposit(f"t{n}", "PAYROLL", 100 * n, date(2026, 10, n), classification=classification) for n in days]


def record(row: dict[str, object], direction: Direction = "in") -> Transaction | None:
    return reading.deposit_from(entry_from(wire.Transaction.model_validate(row)), direction)


def test_each_direction_asks_for_its_own_type_from_the_start_day(held: HeldConnections) -> None:
    sure = served(DepositSure(rows=rows(5)))
    read(date(2026, 10, 1), "in", "out")
    assert sure.polls() == [{"start_date": "2026-10-01", "type": "income", "per_page": "2", "page": "1"},
                            {"start_date": "2026-10-01", "type": "expense", "per_page": "2", "page": "1"}]


def test_a_household_that_is_read_has_its_connection_marked_answered(held: HeldConnections) -> None:
    served(DepositSure(rows=rows(5)))
    read(date(2026, 10, 1), "in")
    assert held.answers == [1]


def test_a_failed_read_is_not_marked_answered(held: HeldConnections) -> None:
    served(DepositSure(status=500))
    with pytest.raises(FAILED):
        read(date(2026, 10, 1), "in")
    assert held.answers == []


def test_a_household_without_a_connection_is_not_connected(held: HeldConnections) -> None:
    sure = served(DepositSure())
    with pytest.raises(NotConnected):
        asyncio.run(reading.read(HOME + 1, date(2026, 10, 1), ("in",)))
    assert sure.seen == []


def test_a_read_holding_everything_is_through_nothing(held: HeldConnections) -> None:
    served(DepositSure(rows=rows(1, 2, 3, 4)))
    found, through = read(date(2026, 10, 1), "in")
    assert [t.id for t in found] == ["t4", "t3", "t2", "t1"] and through is None


def test_a_read_over_the_pages_held_reads_the_oldest_and_continues_from_the_newest_of_them(held: HeldConnections) -> None:
    sure = served(DepositSure(rows=rows(1, 2, 3, 4, 5)))
    found, through = read(date(2026, 10, 1), "in")
    assert [q["page"] for q in sure.polls()] == ["1", "3", "2"]
    assert [t.id for t in found] == ["t1", "t3", "t2"] and through == date(2026, 10, 3)


def test_a_read_cut_in_one_direction_continues_from_the_earlier_cut(held: HeldConnections) -> None:
    served(DepositSure(rows=[*rows(1, 2, 3, 4, 5), *rows(6, 7, 8, 9, 20, classification="expense")]))
    found, through = read(date(2026, 10, 1), "in", "out")
    assert through == date(2026, 10, 3) and {t.direction for t in found} == {"in", "out"}


def test_a_read_that_is_not_cut_in_one_direction_continues_from_the_cut_one(held: HeldConnections) -> None:
    served(DepositSure(rows=[*rows(6, 7, classification="expense"), *rows(1, 2, 3, 4, 5)]))
    assert read(date(2026, 10, 1), "out", "in")[1] == date(2026, 10, 3)


def test_a_cut_read_that_finds_nothing_continues_from_where_it_began(held: HeldConnections) -> None:
    served(Fixed(body={"transactions": [{"date": "soon", "name": "x"}], "pagination": page(5)}))
    found, through = read(date(2026, 10, 1), "in")
    assert found == [] and through == date(2026, 10, 1)


def test_a_body_without_a_count_is_one_page_and_through_nothing(held: HeldConnections) -> None:
    sure = served(Fixed(body={"transactions": rows(5)}))
    found, through = read(date(2026, 10, 1), "in")
    assert len(found) == 1 and through is None and len(sure.seen) == 1


def test_a_page_not_in_the_shape_is_a_failed_read(held: HeldConnections) -> None:
    served(Fixed(body={"rows": []}))
    with pytest.raises(FAILED) as e:
        read(date(2026, 10, 1), "in")
    assert e.value.reason == UNRECOGNISED


def test_a_record_carries_what_a_criterion_reads() -> None:
    got = record(deposit("t1", "ACH credit", 250_000, DAY, merchant="Acme"))
    assert got == Transaction("t1", DAY, CHECKING, 250_000, True, ("Acme", "ACH credit"), "in")


def test_an_expense_is_unsigned_and_counts_only_going_out() -> None:
    row = deposit("t1", "Rent", 90_000, DAY, classification="expense")
    assert record(row, "out") == Transaction("t1", DAY, CHECKING, 90_000, True, ("Rent",), "out")
    got_in = record(row, "in")
    assert got_in is not None and got_in.counts is False


@pytest.mark.parametrize("flag", ["excluded", "split_parent"])
def test_an_excluded_or_split_parent_does_not_count(flag: str) -> None:
    row = deposit("t1", "x", 100, DAY)
    row[flag] = True
    got = record(row)
    assert got is not None and got.counts is False


def test_a_transfer_does_not_count() -> None:
    got = record(deposit("t1", "x", 100, DAY, transfer=True))
    assert got is not None and got.counts is False


def test_a_row_with_no_merchant_is_named_by_its_own_name_and_a_blank_name_is_no_name() -> None:
    got = record(deposit("t1", "PAYROLL", 100, DAY))
    assert got is not None and got.names == ("PAYROLL",)
    row = deposit("t1", "", 100, DAY, merchant="Acme")
    got = record(row)
    assert got is not None and got.names == ("Acme",)


def test_a_row_with_no_account_is_in_the_account_with_no_id() -> None:
    row = deposit("t1", "x", 100, DAY, account_id=SAVINGS)
    row["account"] = None
    got = record(row)
    assert got is not None and got.account_id == ""


def test_an_id_is_kept_up_to_eighty_characters() -> None:
    assert record(deposit("x" * 80, "x", 100, DAY)) is not None
    assert record(deposit("x" * 81, "x", 100, DAY)) is None


@pytest.mark.parametrize("field", ["id", "signed_amount_cents"])
def test_a_row_without_an_id_or_an_amount_is_no_record(field: str) -> None:
    row = deposit("t1", "x", 100, DAY)
    row[field] = None
    assert record(row) is None


@pytest.mark.parametrize("day", ["soon", "", "2026-13-40"])
def test_a_row_dated_by_no_day_is_no_record(day: str) -> None:
    row = deposit("t1", "x", 100, DAY)
    row["date"] = day
    assert record(row) is None

