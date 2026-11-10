"""The Sure adapter of the Ledger (`ashley.sure.ledger.SureLedger`) and the Ledger's Null Object: Sure's bodies become
neutral records, a query becomes only the parameters it sets, a failure is the ledger's reason, and a household with no
connection is not connected."""

import asyncio
from collections.abc import Iterator
from datetime import date

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.ledger.ledger import Ledger, NullLedger
from ashley.ledger.model import Entry, LedgerFailed, LedgerUnavailable, NotConnected, TransactionQuery
from ashley.sure.client import Sure
from money_support import CHECKING, GROCERIES, FakeSure, HeldConnections, params_of


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10


@pytest.fixture
def held() -> Iterator[HeldConnections]:
    found = HeldConnections()
    found.connect(HOME)
    services.register(Connections, found)
    yield found


@pytest.fixture
def sure(held: HeldConnections) -> Iterator[FakeSure]:
    fake = FakeSure()
    services.register(Sure, fake.client())
    yield fake


def ledger() -> Ledger:
    return services.get(Ledger)


def test_unwired_there_is_no_ledger_and_nothing_to_read() -> None:
    services.unregister(Ledger)
    assert isinstance(ledger(), NullLedger)
    assert asyncio.run(ledger().connected(HOME)) is False
    with pytest.raises(NotConnected):
        asyncio.run(ledger().accounts(HOME, 5))
    with pytest.raises(NotConnected):
        asyncio.run(ledger().categories(HOME, 5))
    with pytest.raises(NotConnected):
        asyncio.run(ledger().net_worth(HOME))
    with pytest.raises(NotConnected):
        asyncio.run(ledger().transactions(HOME, TransactionQuery(per_page=5)))


def test_a_household_is_connected_when_it_has_sure(sure: FakeSure) -> None:
    assert asyncio.run(ledger().connected(HOME)) is True
    assert asyncio.run(ledger().connected(HOME + 1)) is False
    assert sure.seen == []


def test_connections_that_cannot_be_read_make_the_ledger_unavailable(held: HeldConnections, sure: FakeSure) -> None:
    held.down = True
    with pytest.raises(LedgerUnavailable):
        asyncio.run(ledger().connected(HOME))
    with pytest.raises(LedgerUnavailable):
        asyncio.run(ledger().accounts(HOME, 5))


def test_a_read_for_a_household_with_no_sure_asks_nothing(sure: FakeSure) -> None:
    with pytest.raises(NotConnected):
        asyncio.run(ledger().accounts(HOME + 1, 5))
    assert sure.seen == []


def test_accounts_categories_and_net_worth_are_neutral_records(held: HeldConnections, sure: FakeSure) -> None:
    accounts = asyncio.run(ledger().accounts(HOME, 7))
    assert [(a.id, a.name, a.balance, a.type, a.classification) for a in accounts.rows] == [
        (CHECKING, "Checking", "$1,234.56", "depository", "asset"), ("a2", "Visa", "$300.00", "depository", "liability")]
    assert accounts.total == 2 and params_of(sure.seen, "/api/v1/accounts") == {"per_page": "7"}
    categories = asyncio.run(ledger().categories(HOME, 9))
    assert [(c.id, c.name, c.parent) for c in categories.rows] == [(GROCERIES, "Groceries", "Food")]
    assert params_of(sure.seen, "/api/v1/categories") == {"per_page": "9"}
    worth = asyncio.run(ledger().net_worth(HOME))
    assert (worth.net_worth, worth.assets, worth.liabilities, worth.currency) == ("$934.56", "$1,234.56", "$300.00", "USD")
    assert params_of(sure.seen, "/api/v1/balance_sheet") == {}
    assert held.answers == [1, 1, 1]


def test_a_transaction_is_an_entry_with_unsigned_cents(sure: FakeSure) -> None:
    got = asyncio.run(ledger().transactions(HOME, TransactionQuery(per_page=5)))
    assert got.total == 2
    assert got.rows[0] == Entry(
        id="t-Groceries run", date="2026-10-30", name="Groceries run", amount="$12.34", cents=1234,
        classification="expense", account_id=CHECKING, account="Checking", category="Groceries",
        merchant="Corner Grocer", transfer=False, excluded=False, split=False)
    assert got.rows[1].transfer is True and got.rows[1].category is None


def test_a_query_asks_only_for_what_it_sets(sure: FakeSure) -> None:
    asyncio.run(ledger().transactions(HOME, TransactionQuery(per_page=5)))
    assert params_of(sure.seen, "/api/v1/transactions") == {"per_page": "5"}
    sure.seen.clear()
    asyncio.run(ledger().transactions(HOME, TransactionQuery(
        per_page=3, start="2026-10-01", end="2026-10-31", account_id=CHECKING, category_id=GROCERIES, search="soop",
        kind="expense", page=2)))
    assert params_of(sure.seen, "/api/v1/transactions") == {
        "per_page": "3", "start_date": "2026-10-01", "end_date": "2026-10-31", "account_id": CHECKING,
        "category_id": GROCERIES, "search": "soop", "type": "expense", "page": "2"}


@pytest.mark.parametrize(("status", "raw", "reason"), [
    (401, None, "refused"), (403, None, "refused"), (500, None, "unreachable"), (302, None, "unreachable"),
    (404, None, "unrecognised"), (200, b"<html>", "unrecognised")])
def test_a_failure_is_the_ledgers_reason_and_is_not_marked_answered(held: HeldConnections, sure: FakeSure, status: int,
                                                                    raw: bytes | None, reason: str) -> None:
    sure.status, sure.raw = status, raw
    with pytest.raises(LedgerFailed) as e:
        asyncio.run(ledger().accounts(HOME, 5))
    assert e.value.reason == reason and held.answers == []


def test_a_body_in_no_known_shape_is_unrecognised(sure: FakeSure) -> None:
    sure.answers["/api/v1/transactions"] = {"rows": []}
    with pytest.raises(LedgerFailed) as e:
        asyncio.run(ledger().transactions(HOME, TransactionQuery(per_page=1, start=date(2026, 1, 1).isoformat())))
    assert e.value.reason == "unrecognised"


def test_a_row_the_backend_leaves_fields_out_of_has_them_none(sure: FakeSure) -> None:
    sure.answers["/api/v1/transactions"] = {"transactions": [{"date": "2026-10-01", "name": "x"}]}
    got = asyncio.run(ledger().transactions(HOME, TransactionQuery(per_page=1)))
    assert got.total is None and got.rows == (Entry(None, "2026-10-01", "x", None, None, None, None, None, None, None,
                                                    False, False, False),)
