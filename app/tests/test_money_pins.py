"""What her money tools answer, pinned to the byte before they move behind the ledger port: the exact text of every
error result, the key order of every answer, the page sizes asked of the backend, the row counts logged, the optional
fields left out when the backend omits them, and the tool specs themselves (`money_specs_pin.json`)."""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from ashley import logs, services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.ledger.ledger import Ledger
from ashley.sure.client import Sure
from ashley.sure.ledger import SureLedger
from ashley.tools import money_config
from ashley.tools.money import MoneyTools
from ashley.tools.money_specs import ACCOUNTS, CATEGORIES, INSTRUCTIONS, NAMES, NET_WORTH, TRANSACTIONS, specs
from money_support import CHECKING, FakeSure, HeldConnections, account, page


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10
CONFIG = money_config.load()
SPECS = Path(__file__).with_name("money_specs_pin.json")


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


def ask(name: str, arguments: dict[str, object], config: money_config.MoneyConfig = CONFIG,
        household: int = HOME) -> ToolResult:
    return asyncio.run(MoneyTools(household, config).call(ToolCall("c1", name, arguments)))


def run(name: str, config: money_config.MoneyConfig = CONFIG, household: int = HOME, **arguments: object) -> ToolResult:
    return ask(name, arguments, config, household)


def answers(fake: FakeSure, path: str) -> dict[str, object]:
    """The fake's answer at `path`, typed; changes made to it are the fake's."""
    loose: Any = fake.answers[path]
    typed = dict[str, object](loose)
    fake.answers[path] = typed
    return typed


def test_every_answer_is_the_same_bytes(held: HeldConnections, sure: FakeSure) -> None:
    assert run(ACCOUNTS).content == (
        '{"accounts": [{"id": "0b6f5a3e-1c2d-4e5f-8a9b-0c1d2e3f4a5b", "name": "Checking", "balance": "$1,234.56", '
        '"type": "depository", "classification": "asset"}, {"id": "a2", "name": "Visa", "balance": "$300.00", '
        '"type": "depository", "classification": "liability"}], "cut": false}')
    assert run(TRANSACTIONS).content == (
        '{"transactions": [{"date": "2026-10-30", "name": "Groceries run", "amount": "$12.34", '
        '"classification": "expense", "account": "Checking", "category": "Groceries", "merchant": "Corner Grocer"}, '
        '{"date": "2026-10-29", "name": "To savings", "amount": "$100.00", "classification": "expense", '
        '"account": "Checking", "merchant": "Corner Grocer", "transfer": true}], "cut": false, "matched": 2}')
    assert run(CATEGORIES).content == (
        '{"categories": [{"id": "7d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6", "name": "Groceries", "parent": "Food"}], '
        '"cut": false}')
    assert run(NET_WORTH).content == (
        '{"net_worth": "$934.56", "assets": "$1,234.56", "liabilities": "$300.00", "currency": "USD"}')


def test_a_row_the_backend_leaves_fields_out_of_leaves_them_out(held: HeldConnections, sure: FakeSure) -> None:
    bare_account: dict[str, object] = {"id": "a9", "name": "Cash"}
    bare_row: dict[str, object] = {"date": "2026-10-01", "name": "Gift", "excluded": True, "split_parent": True}
    answers(sure, "/api/v1/accounts")["accounts"] = [bare_account]
    answers(sure, "/api/v1/transactions")["transactions"] = [bare_row]
    del answers(sure, "/api/v1/accounts")["pagination"]
    del answers(sure, "/api/v1/transactions")["pagination"]
    assert run(ACCOUNTS).content == '{"accounts": [{"id": "a9", "name": "Cash"}], "cut": false}'
    assert run(TRANSACTIONS).content == (
        '{"transactions": [{"date": "2026-10-01", "name": "Gift", "excluded": true, "split": true}], "cut": false}')


def test_a_balance_sheet_without_a_currency_names_none(held: HeldConnections, sure: FakeSure) -> None:
    del answers(sure, "/api/v1/balance_sheet")["currency"]
    assert run(NET_WORTH).content == '{"net_worth": "$934.56", "assets": "$1,234.56", "liabilities": "$300.00"}'


def test_categories_without_a_parent_or_a_count_are_not_cut(held: HeldConnections, sure: FakeSure) -> None:
    del answers(sure, "/api/v1/categories")["pagination"]
    answers(sure, "/api/v1/categories")["categories"] = [{"id": "c1", "name": "Rent"}]
    assert run(CATEGORIES).content == '{"categories": [{"id": "c1", "name": "Rent"}], "cut": false}'


def test_categories_say_cut_when_more_exist(held: HeldConnections, sure: FakeSure) -> None:
    answers(sure, "/api/v1/categories")["pagination"] = page(300)
    assert json.loads(run(CATEGORIES).content)["cut"] is True


def test_a_listing_exactly_as_long_as_the_match_is_not_cut(held: HeldConnections, sure: FakeSure) -> None:
    for path in ("/api/v1/accounts", "/api/v1/transactions", "/api/v1/categories"):
        assert json.loads(run(_TOOL[path]).content)["cut"] is False


_TOOL = {"/api/v1/accounts": ACCOUNTS, "/api/v1/transactions": TRANSACTIONS, "/api/v1/categories": CATEGORIES}


def test_accounts_and_categories_ask_their_own_page_size(held: HeldConnections, sure: FakeSure) -> None:
    config = replace(CONFIG, accounts_max=7, categories_max=9)
    run(ACCOUNTS, config)
    run(CATEGORIES, config)
    asked = {path: query for path, query, _ in sure.seen}
    assert asked == {"/api/v1/accounts": {"per_page": "7"}, "/api/v1/categories": {"per_page": "9"}}


def test_the_balance_sheet_is_asked_with_nothing(held: HeldConnections, sure: FakeSure) -> None:
    run(NET_WORTH)
    assert sure.seen[0][:2] == ("/api/v1/balance_sheet", {})


@pytest.mark.parametrize(("status", "raw", "text"), [
    (401, None, "refused: Sure turned the household's key away; someone in the household can replace it in settings"),
    (403, None, "refused: Sure turned the household's key away; someone in the household can replace it in settings"),
    (500, None, "unreachable: Sure did not answer"),
    (404, None, "not_sure: Sure answered with something unexpected"),
    (200, b"<html></html>", "not_sure: Sure answered with something unexpected")])
def test_a_failed_read_says_exactly_this(held: HeldConnections, sure: FakeSure, status: int, raw: bytes | None,
                                         text: str) -> None:
    sure.status, sure.raw = status, raw
    result = run(ACCOUNTS)
    assert (result.content, result.is_error) == (text, True)


def test_the_other_errors_say_exactly_this(held: HeldConnections, sure: FakeSure) -> None:
    assert run("money_transfer").content == "unknown_tool: no tool named money_transfer"
    assert run(ACCOUNTS, household=HOME + 1).content == "not_connected: the household has not connected Sure"
    assert run(TRANSACTIONS, start_date="soon").content == "bad_arguments: start_date is a date, YYYY-MM-DD"
    held.down = True
    assert run(ACCOUNTS).content == "unavailable: the household's connections cannot be read"


@pytest.mark.parametrize(("arguments", "text"), [
    ({"end_date": "x"}, "end_date is a date, YYYY-MM-DD"),
    ({"account_id": "x"}, "account_id is an id as the money tools give it"),
    ({"category_id": "x"}, "category_id is an id as the money tools give it"),
    ({"search": " "}, f"search is some words, at most {CONFIG.search_chars} characters"),
    ({"type": "all"}, "type is income or expense"),
    ({"limit": 0}, f"limit is a whole number from 1 to {CONFIG.transactions_max}")])
def test_a_wrong_argument_names_itself_and_no_value(held: HeldConnections, sure: FakeSure,
                                                    arguments: dict[str, object], text: str) -> None:
    assert ask(TRANSACTIONS, arguments).content == "bad_arguments: " + text


def test_the_edges_of_what_is_accepted(held: HeldConnections, sure: FakeSure) -> None:
    run(TRANSACTIONS, start_date="2026-10-01", account_id=CHECKING.upper(), search="x" * CONFIG.search_chars,
        type="income", limit=CONFIG.transactions_max)
    assert sure.seen[0][1] == {"start_date": "2026-10-01", "account_id": CHECKING.upper(),
                               "search": "x" * CONFIG.search_chars, "type": "income",
                               "per_page": str(CONFIG.transactions_max)}
    sure.seen.clear()
    assert not run(TRANSACTIONS, limit=1).is_error and sure.seen[0][1] == {"per_page": "1"}
    assert run(TRANSACTIONS, account_id=CHECKING + "0").is_error
    assert run(TRANSACTIONS, account_id="x" + CHECKING).is_error
    assert run(TRANSACTIONS, start_date="2026-10-01x").is_error
    assert run(TRANSACTIONS, end_date="20261001").is_error
    assert run(TRANSACTIONS, limit=CONFIG.transactions_max + 1).is_error


def test_the_rows_logged_are_the_rows_shown(held: HeldConnections, sure: FakeSure,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    answers(sure, "/api/v1/categories")["categories"] = [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"},
                                                          {"id": "c3", "name": "C"}]
    answers(sure, "/api/v1/accounts")["accounts"] = [account("a1", "A", "$1.00")]
    logs.setup()
    capsys.readouterr()
    for name in NAMES:
        run(name)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if "event=tools.call" in ln]
    rows = {name: [ln for ln in lines if f"tool={name} " in ln] for name in NAMES}
    assert [(n, len(ls), "rows=%d" % want in ls[0]) for (n, ls), want in zip(rows.items(), (1, 2, 3, 1), strict=True)] == [
        (ACCOUNTS, 1, True), (TRANSACTIONS, 1, True), (CATEGORIES, 1, True), (NET_WORTH, 1, True)]


def test_a_failed_call_logs_its_outcome_and_no_rows(held: HeldConnections, sure: FakeSure,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    sure.status = 500
    logs.setup()
    capsys.readouterr()
    run(ACCOUNTS)
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "event=tools.call" in ln)
    assert "outcome=unreachable" in line and "rows=" not in line


class CountingLedger(SureLedger):
    asked: int = 0

    async def connected(self, household_id: int) -> bool:
        self.asked += 1
        return await super().connected(household_id)


def test_a_turn_asks_whether_the_household_is_connected_once(held: HeldConnections, sure: FakeSure) -> None:
    counting = CountingLedger()
    services.register(Ledger, counting)
    tools = MoneyTools(HOME, CONFIG)
    asyncio.run(tools.catalogue())
    asyncio.run(tools.call(ToolCall("c1", ACCOUNTS, {})))
    asyncio.run(tools.call(ToolCall("c2", NET_WORTH, {})))
    assert counting.asked == 1


def test_the_tool_specs_are_unchanged() -> None:
    now = [{"name": s.name, "description": s.description, "parameters": s.parameters, "reads": s.reads}
           for s in specs(CONFIG)]
    assert {"specs": now, "instructions": INSTRUCTIONS} == json.loads(SPECS.read_text())
