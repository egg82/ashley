"""What a read asks of Sure: a household's own connection, only GETs, and only what the query sets."""

import pytest
from ashley.ledger.model import TransactionQuery
from ledger_blind_support import KEY, TIMEOUT_S, OTHER_BASE, OTHER_KEY, World, other_household, run
from connection_legacy_support import put_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")


def test_a_bare_query_asks_only_for_its_page_size(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=17))
    assert run(db_url, scenario).asked("/api/v1/transactions") == {"per_page": "17"}


def test_every_filter_the_query_sets_reaches_sure_and_none_it_leaves_unset(db_url: str) -> None:
    query = TransactionQuery(per_page=5, start="2026-10-01", end="2026-10-31", account_id="acct-1",
                             category_id="cat-1", search="rent", kind="expense", page=3)

    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, query)
    asked = run(db_url, scenario).asked("/api/v1/transactions")
    assert len(asked) == 8
    assert set(asked.values()) >= {"5", "2026-10-01", "2026-10-31", "acct-1", "cat-1", "rent", "expense", "3"}


@pytest.mark.parametrize("query,value", [
    (TransactionQuery(per_page=4, start="2026-01-02"), "2026-01-02"),
    (TransactionQuery(per_page=4, end="2026-01-03"), "2026-01-03"),
    (TransactionQuery(per_page=4, account_id="a-9"), "a-9"),
    (TransactionQuery(per_page=4, category_id="c-9"), "c-9"),
    (TransactionQuery(per_page=4, search="milk"), "milk"),
    (TransactionQuery(per_page=4, kind="income"), "income"),
    (TransactionQuery(per_page=4, page=2), "2")])
def test_one_filter_adds_exactly_one_parameter(db_url: str, query: TransactionQuery, value: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, query)
    asked = run(db_url, scenario).asked("/api/v1/transactions")
    assert len(asked) == 2 and value in asked.values()


def test_start_and_end_are_different_parameters(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=1, start="2026-01-01", end="2026-02-02"))
    asked = run(db_url, scenario).asked("/api/v1/transactions")
    keys = {v: k for k, v in asked.items()}
    assert keys["2026-01-01"] != keys["2026-02-02"]


def test_income_and_expense_are_different_values_of_one_parameter(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=1, kind="income"))
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=1, kind="expense"))
    income, expense = [q for _, _, q, _, _ in run(db_url, scenario).seen]
    assert income != expense and set(income) == set(expense)


def test_accounts_and_categories_ask_for_the_limit(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.accounts(w.household_id, 12)
        await w.ledger.categories(w.household_id, 34)
    fake = run(db_url, scenario)
    assert fake.asked("/api/v1/accounts") == {"per_page": "12"}
    assert fake.asked("/api/v1/categories") == {"per_page": "34"}


def test_the_parameters_carry_sures_documented_names(db_url: str) -> None:
    query = TransactionQuery(per_page=5, start="2026-10-01", end="2026-10-31", account_id="acct-1",
                             category_id="cat-1", search="rent", kind="expense", page=3)

    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, query)
    assert run(db_url, scenario).asked("/api/v1/transactions") == {
        "start_date": "2026-10-01", "end_date": "2026-10-31", "account_id": "acct-1", "category_id": "cat-1",
        "search": "rent", "type": "expense", "per_page": "5", "page": "3"}


def test_a_set_but_empty_filter_is_still_sent(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=0, search=""))
    asked = run(db_url, scenario).asked("/api/v1/transactions")
    assert asked == {"per_page": "0", "search": ""}


def test_the_balance_sheet_is_asked_with_no_parameters(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.net_worth(w.household_id)
    assert run(db_url, scenario).asked("/api/v1/balance_sheet") == {}


def test_every_request_carries_the_timeout_registration_was_given(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.accounts(w.household_id, 1)
    seen = run(db_url, scenario).timeouts
    assert seen == [{TIMEOUT_S}]


def test_net_worth_asks_the_balance_sheet(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.net_worth(w.household_id)
    fake = run(db_url, scenario)
    assert [p for _, p, _, _, _ in fake.seen] == ["/api/v1/balance_sheet"]


def test_only_gets_are_sent_by_every_read(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.connected(w.household_id)
        await w.ledger.accounts(w.household_id, 1)
        await w.ledger.categories(w.household_id, 1)
        await w.ledger.net_worth(w.household_id)
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=1))
    fake = run(db_url, scenario)
    assert len(fake.seen) == 4 and {m for m, *_ in fake.seen} == {"GET"}


def test_each_household_is_read_with_its_own_base_and_key(db_url: str) -> None:
    async def scenario(w: World) -> None:
        second, person = other_household(db_url, "second")
        await put_of(w.connections, second, "sure", OTHER_BASE, OTHER_KEY, person)
        await w.ledger.accounts(w.household_id, 1)
        await w.ledger.accounts(second, 1)
    fake = run(db_url, scenario)
    assert [(h, k) for _, _, _, k, h in fake.seen] == [("money.test", KEY), ("other.test", OTHER_KEY)]


def test_the_key_travels_in_the_api_key_header_not_the_query(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await w.ledger.transactions(w.household_id, TransactionQuery(per_page=1, search="x"))
    fake = run(db_url, scenario)
    assert KEY not in fake.asked("/api/v1/transactions").values() and fake.seen[0][3] == KEY
