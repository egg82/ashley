"""Her money tools (`tools.money.MoneyTools`) against a fake Sure: nothing offered to a household with no Sure
connection; four reads offered to one that has it; each asks Sure the right endpoint with the household's key and
answers compactly, saying when it was cut; bad arguments ask Sure nothing; Sure refusing, failing, redirecting or
answering something else is an error result, never a raise; the key reaches no result and no log line."""

import asyncio
import json
from collections.abc import Iterator

import pytest
from ashley import logs, services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.sure.client import Sure
from ashley.tools import money_config
from ashley.tools.money import MoneyTools
from ashley.tools.money_specs import ACCOUNTS, CATEGORIES, CATEGORISE, NAMES, NET_WORTH, NOTE, READS, TRANSACTIONS
from ashley.tools.tools import ToolsUnavailable
from money_support import CHECKING, GROCERIES, KEY, FakeSure, HeldConnections, params_of


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10
CONFIG = money_config.load()


@pytest.fixture
def held() -> Iterator[HeldConnections]:
    found = HeldConnections()
    found.connect(HOME)
    services.register(Connections, found)
    yield found
    services.unregister(Connections)


@pytest.fixture
def sure() -> Iterator[FakeSure]:
    fake = FakeSure()
    services.register(Sure, fake.client())
    yield fake
    services.unregister(Sure)


def run(name: str, household: int = HOME, **arguments: object) -> ToolResult:
    return asyncio.run(MoneyTools(household, CONFIG).call(ToolCall("c1", name, arguments)))


def body(result: ToolResult) -> dict[str, object]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def test_a_household_without_sure_is_offered_nothing(held: HeldConnections, sure: FakeSure) -> None:
    catalogue = asyncio.run(MoneyTools(HOME + 1, CONFIG).catalogue())
    assert catalogue.specs == () and catalogue.instructions is None
    assert sure.seen == []


def test_a_household_with_sure_is_offered_four_reads_and_two_changes(held: HeldConnections, sure: FakeSure) -> None:
    catalogue = asyncio.run(MoneyTools(HOME, CONFIG).catalogue())
    assert [s.name for s in catalogue.specs] == list(NAMES)
    assert [s.name for s in catalogue.specs if not s.reads] == [CATEGORISE, NOTE]
    assert catalogue.instructions


def test_connections_that_cannot_be_read_make_the_source_unreachable(held: HeldConnections) -> None:
    held.down = True
    with pytest.raises(ToolsUnavailable):
        asyncio.run(MoneyTools(HOME, CONFIG).catalogue())
    result = run(ACCOUNTS)
    assert result.is_error and result.content.startswith("unavailable")


def test_accounts_are_read_with_the_households_key(held: HeldConnections, sure: FakeSure) -> None:
    got = body(run(ACCOUNTS))
    assert got == {"accounts": [
        {"id": CHECKING, "name": "Checking", "balance": "$1,234.56", "type": "depository", "classification": "asset"},
        {"id": "a2", "name": "Visa", "balance": "$300.00", "type": "depository", "classification": "liability"}],
        "cut": False}
    assert sure.seen == [("/api/v1/accounts", {"per_page": str(CONFIG.accounts_max)}, KEY)]
    assert held.answers == [1]


def test_an_answer_holding_less_than_sure_has_says_cut(held: HeldConnections, sure: FakeSure) -> None:
    answers = sure.answers["/api/v1/accounts"]
    assert isinstance(answers, dict)
    answers["pagination"] = {"total_count": 250}
    assert body(run(ACCOUNTS))["cut"] is True


def test_transactions_pass_their_filters_to_sure(held: HeldConnections, sure: FakeSure) -> None:
    got = body(run(TRANSACTIONS, start_date="2026-10-01", end_date="2026-10-31", account_id=CHECKING,
                   category_id=GROCERIES, search=" soopers ", type="expense", limit=10))
    assert params_of(sure.seen, "/api/v1/transactions") == {
        "start_date": "2026-10-01", "end_date": "2026-10-31", "account_id": CHECKING, "category_id": GROCERIES,
        "search": "soopers", "type": "expense", "per_page": "10"}
    assert got["matched"] == 2 and got["cut"] is False
    assert got["transactions"] == [
        {"id": "t-Groceries run", "date": "2026-10-30", "name": "Groceries run", "amount": "$12.34",
         "classification": "expense", "account": "Checking", "category": "Groceries", "merchant": "Corner Grocer"},
        {"id": "t-To savings", "date": "2026-10-29", "name": "To savings", "amount": "$100.00", "classification": "expense",
         "account": "Checking", "merchant": "Corner Grocer", "transfer": True}]


def test_transactions_without_a_limit_take_the_default(held: HeldConnections, sure: FakeSure) -> None:
    body(run(TRANSACTIONS))
    assert params_of(sure.seen, "/api/v1/transactions") == {"per_page": str(CONFIG.transactions_default)}


def test_more_matched_than_shown_is_cut(held: HeldConnections, sure: FakeSure) -> None:
    answers = sure.answers["/api/v1/transactions"]
    assert isinstance(answers, dict)
    answers["pagination"] = {"total_count": 41}
    got = body(run(TRANSACTIONS, limit=2))
    assert got["matched"] == 41 and got["cut"] is True


@pytest.mark.parametrize("arguments", [
    {"start_date": "2026-13-01"}, {"end_date": "yesterday"}, {"start_date": "2026-1-5"}, {"account_id": "checking"},
    {"category_id": 7}, {"search": ""}, {"search": "x" * (CONFIG.search_chars + 1)}, {"type": "transfer"},
    {"limit": 0}, {"limit": CONFIG.transactions_max + 1}, {"limit": True}, {"limit": "5"}])
def test_bad_arguments_ask_sure_nothing(held: HeldConnections, sure: FakeSure, arguments: dict[str, object]) -> None:
    result = asyncio.run(MoneyTools(HOME, CONFIG).call(ToolCall("c1", TRANSACTIONS, arguments)))
    assert result.is_error and result.content.startswith("bad_arguments")
    assert sure.seen == []


def test_categories_name_their_parent(held: HeldConnections, sure: FakeSure) -> None:
    assert body(run(CATEGORIES)) == {"categories": [{"id": GROCERIES, "name": "Groceries", "parent": "Food"}],
                                     "cut": False}


def test_net_worth_is_sures_balance_sheet(held: HeldConnections, sure: FakeSure) -> None:
    assert body(run(NET_WORTH)) == {"net_worth": "$934.56", "assets": "$1,234.56", "liabilities": "$300.00",
                                    "currency": "USD"}
    assert sure.seen[0][0] == "/api/v1/balance_sheet"


@pytest.mark.parametrize(("status", "raw", "outcome"), [
    (401, None, "refused"), (403, None, "refused"), (500, None, "unreachable"), (302, None, "unreachable"),
    (404, None, "not_sure"), (200, b"<html>login</html>", "not_sure")])
def test_sure_failing_is_an_error_result(held: HeldConnections, sure: FakeSure, status: int, raw: bytes | None,
                                         outcome: str) -> None:
    sure.status, sure.raw = status, raw
    result = run(ACCOUNTS)
    assert result.is_error and result.content.startswith(outcome)
    assert len(sure.seen) == 1, "a redirect is not followed"
    assert held.answers == []


def test_a_body_not_in_sures_shape_is_not_sure(held: HeldConnections, sure: FakeSure) -> None:
    sure.answers["/api/v1/accounts"] = {"items": []}
    result = run(ACCOUNTS)
    assert result.is_error and result.content.startswith("not_sure")


def test_a_household_that_has_not_connected_gets_an_error_not_a_call(held: HeldConnections, sure: FakeSure) -> None:
    result = run(ACCOUNTS, household=HOME + 1)
    assert result.is_error and result.content.startswith("not_connected")
    assert sure.seen == []


def test_an_unknown_tool_is_an_error(held: HeldConnections, sure: FakeSure) -> None:
    result = run("money_transfer")
    assert result.is_error and sure.seen == []


def test_the_key_reaches_no_result_and_no_log(held: HeldConnections, sure: FakeSure,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    results = [run(name) for name in READS]
    sure.status = 401
    results.append(run(ACCOUNTS))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert sum("event=sure.get" in ln for ln in lines) == len(READS) + 1, "the probe saw every call's line"
    assert not any(KEY in r.content for r in results)
    assert not any(KEY in ln or "money.test" in ln for ln in lines)
