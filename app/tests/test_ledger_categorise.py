"""`Ledger.categorise` on the Sure adapter against the fake Sure, and on the Null Object: each transaction is put to
Sure with only the category, in order, and a read afterwards shows it there; a category that is not the household's
changes nothing; a transaction Sure does not have, or will not change, is that one's outcome while the rest are set; a
key that may only read is refused; an id stays one path segment; the log carries counts and no names; no ledger, or no
Sure for the household, refuses without asking."""

import asyncio
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from ashley import logs, services
from ashley.connections.connections import Connections
from ashley.ledger.ledger import Ledger, NullLedger
from ashley.ledger.model import LedgerFailed, NotConnected, TransactionQuery, UnknownCategory
from ashley.sure.client import HttpSure, Sure
from money_support import GROCERIES, KEY, FakeSure, HeldConnections, transaction

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10
FUEL = "4c3b2a19-8d7e-4f6a-9b5c-1d2e3f405162"
T1 = "a1b2c3d4-0000-4000-8000-000000000001"
T2 = "a1b2c3d4-0000-4000-8000-000000000002"
T3 = "a1b2c3d4-0000-4000-8000-000000000003"
MISSING = "a1b2c3d4-0000-4000-8000-0000000000ff"


@pytest.fixture
def held() -> Iterator[HeldConnections]:
    found = HeldConnections()
    found.connect(HOME)
    services.register(Connections, found)
    yield found


@pytest.fixture
def sure(held: HeldConnections) -> Iterator[FakeSure]:
    fake = FakeSure()
    rows = fake.answers["/api/v1/transactions"]
    assert isinstance(rows, dict)
    rows["transactions"] = [{**transaction(f"Shop {i}", "$1.00", "2026-10-30"), "id": t}
                            for i, t in enumerate((T1, T2, T3))]
    categories: Any = fake.answers["/api/v1/categories"]
    categories["categories"].append({"id": FUEL, "name": "Fuel", "color": "#f00", "icon": "fuel", "parent": None,
                                     "subcategories_count": 0})
    services.register(Sure, fake.client())
    yield fake


def categorise(category: str, *ids: str, household: int = HOME) -> dict[str, str]:
    return dict(asyncio.run(services.get(Ledger).categorise(household, category, ids)))


def categories_now() -> dict[str | None, str | None]:
    page = asyncio.run(services.get(Ledger).transactions(HOME, TransactionQuery(per_page=10)))
    return {e.id: e.category for e in page.rows}


def test_each_transaction_is_set_in_order_with_only_its_category_and_reads_back(held: HeldConnections,
                                                                                sure: FakeSure) -> None:
    assert categorise(FUEL, T2, T1) == {T2: "set", T1: "set"}
    assert sure.written == [(f"/api/v1/transactions/{T2}", {"transaction": {"category_id": FUEL}}),
                            (f"/api/v1/transactions/{T1}", {"transaction": {"category_id": FUEL}})]
    assert categories_now() == {T1: "Fuel", T2: "Fuel", T3: None}
    assert {k for _, _, k in sure.seen} == {KEY} and held.answers


def test_a_category_not_the_households_changes_nothing(sure: FakeSure) -> None:
    with pytest.raises(UnknownCategory):
        categorise("ffffffff-ffff-4fff-8fff-ffffffffffff", T1)
    assert sure.written == []
    assert categories_now()[T1] is None


def test_a_missing_or_unchangeable_transaction_is_its_own_outcome_and_the_rest_are_set(sure: FakeSure) -> None:
    sure.split_parts.add(T2)
    assert categorise(GROCERIES, T1, MISSING, T2, T3) == {T1: "set", MISSING: "not_found", T2: "rejected", T3: "set"}
    assert categories_now() == {T1: "Groceries", T2: None, T3: "Groceries"}


def test_a_key_that_may_only_read_is_refused(sure: FakeSure) -> None:
    sure.reads_only = True
    with pytest.raises(LedgerFailed) as failed:
        categorise(FUEL, T1)
    assert failed.value.reason == "refused"
    assert categories_now()[T1] is None


def test_sure_failing_part_way_is_a_failure_not_an_outcome(sure: FakeSure) -> None:
    sure.status = 500
    with pytest.raises(LedgerFailed) as failed:
        categorise(FUEL, T1)
    assert failed.value.reason == "unreachable"


def test_an_id_stays_one_path_segment(held: HeldConnections) -> None:
    paths: list[bytes] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.raw_path)
        if request.method == "GET":
            return httpx2.Response(200, json={"id": FUEL, "name": "Fuel"})
        return httpx2.Response(200, json={"id": T1, "date": "2026-10-30", "name": "x"})

    services.register(Sure, HttpSure(httpx2.AsyncClient(transport=httpx2.MockTransport(handle)), 5))
    categorise("../accounts", "../../x?y")
    assert paths == [b"/api/v1/categories/..%2Faccounts", b"/api/v1/transactions/..%2F..%2Fx%3Fy"]


def test_the_log_carries_counts_and_no_names_or_key(sure: FakeSure, capsys: pytest.CaptureFixture[str]) -> None:
    sure.split_parts.add(T3)
    logs.setup()
    capsys.readouterr()
    categorise(FUEL, T1, T2, T3, MISSING)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    done = [ln for ln in lines if "event=sure.categorised" in ln]
    assert len(done) == 1 and "set=2" in done[0] and "rejected=1" in done[0] and "not_found=1" in done[0]
    assert sum("event=sure.put" in ln for ln in lines) == 4
    assert not any(word in ln for ln in lines for word in ("Fuel", "Shop", KEY, "money.test", "$1.00"))


def test_no_ledger_and_no_sure_refuse_without_asking(sure: FakeSure) -> None:
    with pytest.raises(NotConnected):
        categorise(FUEL, T1, household=HOME + 1)
    assert sure.seen == []
    services.unregister(Ledger)
    assert isinstance(services.get(Ledger), NullLedger)
    with pytest.raises(NotConnected):
        categorise(FUEL, T1)
    assert sure.seen == []
