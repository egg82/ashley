"""`money_categorise` end to end through `MoneyTools` against the fake Sure: it is offered as the one change, not a
read, so a reads-only turn loses it; it sets the transactions `money_transactions` named, and the next read shows the
category; wrong arguments and a category that is not the household's change nothing; a key that may only read is told
apart from Sure turning the household's key away; the row count logged is how many were set."""

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
from ashley.tools.money_specs import CATEGORISE, TRANSACTIONS
from ashley.tools.reading import Reading
from money_support import GROCERIES, FakeSure, HeldConnections, transaction

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10
CONFIG = money_config.load()
T1 = "b1b2c3d4-0000-4000-8000-000000000001"
T2 = "b1b2c3d4-0000-4000-8000-000000000002"


@pytest.fixture
def sure() -> Iterator[FakeSure]:
    held = HeldConnections()
    held.connect(HOME)
    services.register(Connections, held)
    fake = FakeSure()
    rows = fake.answers["/api/v1/transactions"]
    assert isinstance(rows, dict)
    rows["transactions"] = [{**transaction(f"Shop {i}", "$1.00", "2026-10-30"), "id": t} for i, t in enumerate((T1, T2))]
    services.register(Sure, fake.client())
    yield fake


def run(name: str, **arguments: object) -> ToolResult:
    return asyncio.run(MoneyTools(HOME, CONFIG).call(ToolCall("c1", name, arguments)))


def test_the_ids_she_reads_are_the_ids_she_categorises(sure: FakeSure) -> None:
    listed = json.loads(run(TRANSACTIONS).content)["transactions"]
    ids = [t["id"] for t in listed]
    got = run(CATEGORISE, transaction_ids=ids, category_id=GROCERIES)
    assert not got.is_error and json.loads(got.content) == {"set": 2}
    assert [t.get("category") for t in json.loads(run(TRANSACTIONS).content)["transactions"]] == ["Groceries"] * 2


def test_an_id_named_twice_is_put_once(sure: FakeSure) -> None:
    assert not run(CATEGORISE, transaction_ids=[T1, T1], category_id=GROCERIES).is_error
    assert [p for p, _ in sure.written] == [f"/api/v1/transactions/{T1}"]


def test_what_was_not_set_is_named_by_id(sure: FakeSure) -> None:
    sure.split_parts.add(T2)
    missing = "b1b2c3d4-0000-4000-8000-0000000000ff"
    got = json.loads(run(CATEGORISE, transaction_ids=[T1, missing, T2], category_id=GROCERIES).content)
    assert got == {"set": 1, "not_found": [missing], "rejected": [T2]}


@pytest.mark.parametrize("arguments", [
    {"transaction_ids": [T1]},
    {"transaction_ids": [T1], "category_id": "groceries"},
    {"transaction_ids": [], "category_id": GROCERIES},
    {"transaction_ids": T1, "category_id": GROCERIES},
    {"transaction_ids": ["t-Shop 0"], "category_id": GROCERIES},
    {"transaction_ids": [T1] + [f"b1b2c3d4-0000-4000-8000-{i:012d}" for i in range(CONFIG.categorise_max)],
     "category_id": GROCERIES},
])
def test_wrong_arguments_ask_sure_nothing(sure: FakeSure, arguments: dict[str, object]) -> None:
    got = run(CATEGORISE, **arguments)
    assert got.is_error and sure.seen == [] and sure.written == []


def test_the_most_ids_allowed_are_put(sure: FakeSure) -> None:
    ids = [f"b1b2c3d4-0000-4000-8000-{i:012d}" for i in range(CONFIG.categorise_max)]
    assert not run(CATEGORISE, transaction_ids=ids, category_id=GROCERIES).is_error
    assert len(sure.written) == CONFIG.categorise_max


def test_a_category_not_the_households_is_a_bad_argument_and_nothing_is_put(sure: FakeSure) -> None:
    got = run(CATEGORISE, transaction_ids=[T1], category_id="ffffffff-ffff-4fff-8fff-ffffffffffff")
    assert got.is_error and "money_categories" in got.content and sure.written == []


def test_a_key_that_may_only_read_says_so(sure: FakeSure) -> None:
    sure.reads_only = True
    got = run(CATEGORISE, transaction_ids=[T1], category_id=GROCERIES)
    assert got.is_error and "may write" in got.content
    sure.reads_only, sure.status = False, 401
    assert "may write" not in run("money_accounts").content


def test_it_is_the_one_change_and_a_reads_only_turn_is_not_offered_it(sure: FakeSure) -> None:
    offered = asyncio.run(MoneyTools(HOME, CONFIG).catalogue()).specs
    changes = [s for s in offered if not s.reads]
    assert [(s.name, s.outside, s.tier) for s in changes] == [(CATEGORISE, False, "asks")]
    reading = asyncio.run(Reading(MoneyTools(HOME, CONFIG)).catalogue()).specs
    assert CATEGORISE not in [s.name for s in reading] and TRANSACTIONS in [s.name for s in reading]


def test_the_rows_logged_are_how_many_were_set(sure: FakeSure, capsys: pytest.CaptureFixture[str]) -> None:
    sure.split_parts.add(T2)
    logs.setup()
    capsys.readouterr()
    run(CATEGORISE, transaction_ids=[T1, T2], category_id=GROCERIES)
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "event=tools.call" in ln)
    assert f"tool={CATEGORISE} " in line and "rows=1" in line and "Groceries" not in line
