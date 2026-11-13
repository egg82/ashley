"""The Ledger over a Sure connection answers the port's neutral records, mapped from Sure's REST shapes."""

import pytest
from ashley.ledger.model import Account, Category, Entry, NetWorth, Page, TransactionQuery
from ledger_blind_support import AMOUNT, CHECKING, GROCERIES, PAYEE, FakeSure, World, run, transaction


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")


def test_accounts_are_neutral_records_with_the_backends_balance_text(db_url: str) -> None:
    async def scenario(w: World) -> None:
        page = await w.ledger.accounts(w.household_id, 25)
        assert isinstance(page, Page)
        assert page.rows == (Account(CHECKING, "Checking", "$1,234.56", "depository", "asset", 123_456),
                             Account("a2", "Visa", "-$300.00", "depository", "liability", -30_000))
        assert page.total == 7
    run(db_url, scenario)


def test_an_account_field_the_backend_leaves_out_is_none(db_url: str) -> None:
    fake = FakeSure()
    fake.answers["/api/v1/accounts"] = {"accounts": [{"id": "a", "name": "Bare"}]}

    async def scenario(w: World) -> None:
        page = await w.ledger.accounts(w.household_id, 5)
        assert page.rows == (Account("a", "Bare", None, None, None),)
        assert page.total is None
    run(db_url, scenario, fake)


def test_categories_carry_their_parents_name(db_url: str) -> None:
    async def scenario(w: World) -> None:
        page = await w.ledger.categories(w.household_id, 25)
        assert page.rows == (Category(GROCERIES, "Groceries", "Food"), Category("c2", "Rent", None))
        assert page.total == 2
    run(db_url, scenario)


def test_net_worth_is_the_balance_sheet_as_shown_with_its_currency(db_url: str) -> None:
    async def scenario(w: World) -> None:
        assert await w.ledger.net_worth(w.household_id) == NetWorth("$934.56", "$1,234.56", "$300.00", "USD")
    run(db_url, scenario)


def test_a_net_worth_without_a_currency_has_none(db_url: str) -> None:
    fake = FakeSure()
    sheet = fake.answers["/api/v1/balance_sheet"]
    assert isinstance(sheet, dict)
    del sheet["currency"]

    async def scenario(w: World) -> None:
        assert (await w.ledger.net_worth(w.household_id)).currency is None
    run(db_url, scenario, fake)


def test_a_transaction_is_an_entry_in_the_ledgers_terms(db_url: str) -> None:
    async def scenario(w: World) -> None:
        page = await w.ledger.transactions(w.household_id, TransactionQuery(per_page=10))
        assert page.total == 41
        assert page.rows == (Entry(id="t-Groceries run", date="2026-10-30", name="Groceries run", amount=AMOUNT,
                                   cents=1234, classification="expense", account_id=CHECKING, account="Checking",
                                   category="Groceries", merchant=PAYEE, transfer=False, excluded=False,
                                   split=False),)
    run(db_url, scenario)


def test_cents_are_unsigned_whichever_way_the_money_moved(db_url: str) -> None:
    income = transaction("Pay", "$50.00")
    income.update(signed_amount_cents=5000, classification="income")
    fake = FakeSure()
    fake.answers["/api/v1/transactions"] = {"transactions": [income, transaction("Fee")]}

    async def scenario(w: World) -> None:
        rows = (await w.ledger.transactions(w.household_id, TransactionQuery(per_page=10))).rows
        assert [(e.cents, e.classification) for e in rows] == [(5000, "income"), (1234, "expense")]
    run(db_url, scenario, fake)


def test_transfer_excluded_and_split_flags_follow_the_backend(db_url: str) -> None:
    moved = transaction("Move")
    moved["transfer"] = {"id": "x"}
    left_out = transaction("Out")
    left_out["excluded"] = True
    parent = transaction("Parent")
    parent["split_parent"] = True
    fake = FakeSure()
    fake.answers["/api/v1/transactions"] = {"transactions": [moved, left_out, parent, transaction("Plain")]}

    async def scenario(w: World) -> None:
        rows = (await w.ledger.transactions(w.household_id, TransactionQuery(per_page=10))).rows
        assert [(e.transfer, e.excluded, e.split) for e in rows] == [
            (True, False, False), (False, True, False), (False, False, True), (False, False, False)]
    run(db_url, scenario, fake)


def test_an_entry_the_backend_gives_only_a_date_and_name_has_every_other_field_none(db_url: str) -> None:
    fake = FakeSure()
    fake.answers["/api/v1/transactions"] = {"transactions": [{"date": "2026-10-01", "name": "Cash"}]}

    async def scenario(w: World) -> None:
        rows = (await w.ledger.transactions(w.household_id, TransactionQuery(per_page=10))).rows
        assert rows == (Entry(id=None, date="2026-10-01", name="Cash", amount=None, cents=None, classification=None,
                              account_id=None, account=None, category=None, merchant=None, transfer=False,
                              excluded=False, split=False),)
    run(db_url, scenario, fake)


def test_fields_the_ledger_does_not_name_are_ignored(db_url: str) -> None:
    row = transaction()
    row["something_new_in_a_later_sure"] = {"nested": [1, 2]}
    fake = FakeSure()
    fake.answers["/api/v1/transactions"] = {"transactions": [row], "pagination": {"total_count": 1, "extra": True}}

    async def scenario(w: World) -> None:
        page = await w.ledger.transactions(w.household_id, TransactionQuery(per_page=10))
        assert len(page.rows) == 1 and page.total == 1
    run(db_url, scenario, fake)


def test_an_empty_page_is_a_page_not_an_error(db_url: str) -> None:
    fake = FakeSure()
    fake.answers["/api/v1/transactions"] = {"transactions": [], "pagination": {"total_count": 0}}

    async def scenario(w: World) -> None:
        page = await w.ledger.transactions(w.household_id, TransactionQuery(per_page=10))
        assert page.rows == () and page.total == 0
    run(db_url, scenario, fake)


def test_rows_are_a_tuple(db_url: str) -> None:
    async def scenario(w: World) -> None:
        assert isinstance((await w.ledger.accounts(w.household_id, 3)).rows, tuple)
        assert isinstance((await w.ledger.categories(w.household_id, 3)).rows, tuple)
        assert isinstance((await w.ledger.transactions(w.household_id, TransactionQuery(per_page=3))).rows, tuple)
    run(db_url, scenario)
