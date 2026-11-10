"""Her money tools (`tools.money.MoneyTools`): offered only to a household with a connection, read with that
household's own key, capped and marked `cut`, reads only, and the key in no result or log."""

import asyncio
import json
from collections.abc import Iterator

import httpx2
import pytest
from ashley import logs, services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.sure.client import HttpSure, Sure
from ashley.tools import money_config
from ashley.tools.money import MoneyTools
from money_support import KEY, FakeSure, HeldConnections


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

CONFIG = money_config.load()
NAMES = ["money_accounts", "money_transactions", "money_categories", "money_net_worth"]
OTHER_KEY = "the-other-households-key"


@pytest.fixture
def held() -> Iterator[HeldConnections]:
    found = HeldConnections()
    found.connect(10)
    found.connect(20, "https://other.test", OTHER_KEY)
    services.register(Connections, found)
    yield found


@pytest.fixture
def sure(held: HeldConnections) -> Iterator[FakeSure]:
    fake = FakeSure()
    services.register(Sure, fake.client())
    yield fake


def call(name: str, household: int = 10, **arguments: object) -> ToolResult:
    return asyncio.run(MoneyTools(household, CONFIG).call(ToolCall("c", name, arguments)))


def test_a_household_with_no_connection_is_offered_nothing_and_cannot_call(held: HeldConnections,
                                                                           sure: FakeSure) -> None:
    assert asyncio.run(MoneyTools(30, CONFIG).catalogue()).specs == ()
    result = call("money_accounts", 30)
    assert result.is_error and sure.seen == []


def test_a_connected_household_is_offered_the_four_read_tools(held: HeldConnections, sure: FakeSure) -> None:
    specs = asyncio.run(MoneyTools(10, CONFIG).catalogue()).specs
    assert sorted(s.name for s in specs) == sorted(NAMES) and all(s.reads for s in specs)


@pytest.mark.parametrize("name", NAMES)
def test_every_tool_reads_with_its_own_households_key(held: HeldConnections, sure: FakeSure, name: str) -> None:
    assert not call(name).is_error
    assert sure.seen and {key for _, _, key in sure.seen} == {KEY}


def test_two_households_never_share_a_key_or_a_base(held: HeldConnections) -> None:
    hits: list[tuple[str, str, str | None]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        hits.append((request.url.host, request.url.path, request.headers.get("x-api-key")))
        return httpx2.Response(200, json=FakeSure().answers[request.url.path])

    services.register(Sure, HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), 5))
    call("money_accounts", 10)
    call("money_accounts", 20)
    assert hits == [("money.test", "/api/v1/accounts", KEY), ("other.test", "/api/v1/accounts", OTHER_KEY)]


def test_only_gets_are_sent(held: HeldConnections) -> None:
    methods: set[str] = set()

    def handle(request: httpx2.Request) -> httpx2.Response:
        methods.add(request.method)
        return httpx2.Response(200, json=FakeSure().answers[request.url.path])

    services.register(Sure, HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), 5))
    for name in NAMES:
        call(name)
    assert methods == {"GET"}


def test_a_result_holding_less_than_sure_has_says_cut(held: HeldConnections, sure: FakeSure) -> None:
    assert json.loads(call("money_accounts").content)["cut"] is False
    sure.answers["/api/v1/accounts"] = {"accounts": [], "pagination": {"total_count": CONFIG.accounts_max + 50}}
    assert json.loads(call("money_accounts").content)["cut"] is True


def test_transactions_never_ask_sure_for_more_than_the_cap(held: HeldConnections, sure: FakeSure) -> None:
    call("money_transactions", limit=100000)
    call("money_transactions", limit=CONFIG.transactions_max)
    call("money_transactions")
    asked = [int(q["per_page"]) for p, q, _ in sure.seen if p == "/api/v1/transactions"]
    assert asked and max(asked) <= CONFIG.transactions_max


@pytest.mark.parametrize("arguments", [{"start_date": "yesterday"}, {"end_date": "2026-13-45"}])
def test_bad_arguments_are_an_error_that_asks_sure_nothing(held: HeldConnections, sure: FakeSure,
                                                           arguments: dict[str, object]) -> None:
    result = asyncio.run(MoneyTools(10, CONFIG).call(ToolCall("c", "money_transactions", arguments)))
    assert result.is_error and sure.seen == []
    for value in arguments.values():
        assert str(value) not in result.content


def test_an_unknown_tool_is_an_error_not_a_raise(held: HeldConnections, sure: FakeSure) -> None:
    result = call("money_transfer", amount=5)
    assert result.is_error and sure.seen == []


@pytest.mark.parametrize("fake", [FakeSure(status=401), FakeSure(status=500), FakeSure(status=302),
                                  FakeSure(raw=b"<html>")])
def test_sure_failing_is_an_error_result_with_no_key(held: HeldConnections, fake: FakeSure) -> None:
    services.register(Sure, fake.client())
    result = call("money_accounts")
    assert result.is_error and KEY not in result.content


def test_the_key_is_in_no_result_and_no_log_line(held: HeldConnections, sure: FakeSure,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    results = [call(n) for n in NAMES]
    sure.status = 401
    results.append(call("money_accounts"))
    out = capsys.readouterr()
    assert "tools.call" in out.out
    assert all(KEY not in r.content for r in results) and KEY not in out.out + out.err
    assert "Groceries" not in out.out + out.err


def test_a_successful_read_marks_the_connection_answered(held: HeldConnections, sure: FakeSure) -> None:
    call("money_net_worth")
    assert len(held.answers) == 1
    sure.status = 500
    call("money_net_worth")
    assert len(held.answers) == 1
