"""The port's errors: LedgerFailed(reason), LedgerUnavailable, NotConnected, and the Null default."""

import asyncio
import os
from collections.abc import Awaitable, Callable

import pytest
from ashley import services
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.model import Connection, Holder, Kind, Opened
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.ledger.ledger import Ledger, NullLedger
from ashley.ledger.model import LedgerFailed, LedgerUnavailable, NotConnected, TransactionQuery
from ledger_blind_support import FakeSure, World, run
from connection_legacy_support import put_of, remove_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

Read = Callable[[Ledger, int], Awaitable[object]]
READS: dict[str, Read] = {
    "accounts": lambda ledger, h: ledger.accounts(h, 5),
    "categories": lambda ledger, h: ledger.categories(h, 5),
    "net_worth": lambda ledger, h: ledger.net_worth(h),
    "transactions": lambda ledger, h: ledger.transactions(h, TransactionQuery(per_page=5)),
}


def reason_of(url: str, read: Read, fake: FakeSure) -> str:
    seen: list[str] = []

    async def scenario(w: World) -> None:
        with pytest.raises(LedgerFailed) as raised:
            await read(w.ledger, w.household_id)
        seen.append(raised.value.args[0] if raised.value.args else str(raised.value))
    run(url, scenario, fake)
    return seen[0]


@pytest.mark.parametrize("name", READS)
def test_a_key_sure_refuses_is_refused(db_url: str, name: str) -> None:
    assert reason_of(db_url, READS[name], FakeSure(key="another-key")) == "refused"


@pytest.mark.parametrize("name", READS)
def test_a_sure_that_cannot_be_reached_is_unreachable(db_url: str, name: str) -> None:
    assert reason_of(db_url, READS[name], FakeSure(down=True)) == "unreachable"


@pytest.mark.parametrize("name", READS)
def test_something_that_is_not_sure_answering_is_unrecognised(db_url: str, name: str) -> None:
    assert reason_of(db_url, READS[name], FakeSure(raw=b"<html>not sure</html>")) == "unrecognised"


@pytest.mark.parametrize("name,path,body", [
    ("accounts", "/api/v1/accounts", {"accounts": "nope"}),
    ("categories", "/api/v1/categories", ["a list"]),
    ("net_worth", "/api/v1/balance_sheet", {"net_worth": {"formatted": "$1"}}),
    ("transactions", "/api/v1/transactions", {"transactions": [{"name": "no date"}]})])
def test_json_of_the_wrong_shape_is_unrecognised(db_url: str, name: str, path: str, body: object) -> None:
    fake = FakeSure()
    fake.answers[path] = body
    assert reason_of(db_url, READS[name], fake) == "unrecognised"


@pytest.mark.parametrize("status,reason", [(401, "refused"), (403, "refused"), (404, "unrecognised"),
                                           (500, "unreachable"), (503, "unreachable")])
def test_each_http_failure_is_the_reason_that_names_it(db_url: str, status: int, reason: str) -> None:
    assert reason_of(db_url, READS["accounts"], FakeSure(status=status)) == reason


@pytest.mark.parametrize("status", [302])
def test_a_redirect_or_server_error_is_a_failure_not_a_page(db_url: str, status: int) -> None:
    assert reason_of(db_url, READS["accounts"], FakeSure(status=status)) in ("refused", "unreachable", "unrecognised")


def test_the_reasons_are_distinct_for_distinct_causes(db_url: str) -> None:
    reasons = {reason_of(db_url, READS["accounts"], f) for f in
               (FakeSure(key="x"), FakeSure(down=True), FakeSure(raw=b"<html>"))}
    assert reasons == {"refused", "unreachable", "unrecognised"}


@pytest.mark.parametrize("name", READS)
def test_a_household_without_a_connection_is_not_connected_and_sure_is_not_asked(db_url: str, name: str) -> None:
    async def scenario(w: World) -> None:
        assert await w.ledger.connected(w.household_id) is False
        with pytest.raises(NotConnected):
            await READS[name](w.ledger, w.household_id)
    assert run(db_url, scenario, connect=False).seen == []


def test_a_connection_of_another_kind_is_not_a_ledger(db_url: str) -> None:
    async def scenario(w: World) -> None:
        await remove_of(w.connections, w.household_id, "sure")
        await put_of(w.connections, w.household_id, "home_assistant", "https://ha.test", "token", w.person_id)
        assert await w.ledger.connected(w.household_id) is False
        with pytest.raises(NotConnected):
            await w.ledger.accounts(w.household_id, 5)
    assert run(db_url, scenario).seen == []


def test_a_household_with_a_connection_is_connected_and_asks_sure_nothing(db_url: str) -> None:
    async def scenario(w: World) -> None:
        assert await w.ledger.connected(w.household_id) is True
    assert run(db_url, scenario).seen == []


def test_the_connection_is_the_households_own(db_url: str) -> None:
    async def scenario(w: World) -> None:
        stranger = w.household_id + 1000
        assert await w.ledger.connected(stranger) is False
        with pytest.raises(NotConnected):
            await w.ledger.accounts(stranger, 5)
    assert run(db_url, scenario).seen == []


class Unreadable(Connections):
    """A Connections whose store cannot be read."""

    @classmethod
    def null(cls) -> "Connections":
        return cls()

    def can_open(self) -> bool:
        return True

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        raise ConnectionsUnavailable("down")

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        raise ConnectionsUnavailable("down")

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        raise ConnectionsUnavailable("down")

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        raise ConnectionsUnavailable("down")

    async def relabel(self, connection_id: int, household_id: int, person_id: int,
                      label: str) -> Connection | None:
        raise ConnectionsUnavailable("down")

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        raise ConnectionsUnavailable("down")

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        raise ConnectionsUnavailable("down")

    async def answered(self, connection_id: int) -> None:
        raise ConnectionsUnavailable("down")


@pytest.mark.parametrize("name", [*READS, "connected"])
def test_a_link_that_cannot_be_read_is_unavailable(db_url: str, name: str) -> None:
    async def scenario(w: World) -> None:
        services.register(Connections, Unreadable())
        call: Read = (lambda ledger, h: ledger.connected(h)) if name == "connected" else READS[name]
        with pytest.raises(LedgerUnavailable):
            await call(w.ledger, w.household_id)
    assert run(db_url, scenario).seen == []


def test_a_key_that_does_not_open_is_unavailable_not_a_wrong_key(db_url: str) -> None:
    async def scenario(w: World) -> None:
        services.register(Connections, PostgresConnections(w.database, Sealer({1: os.urandom(32)}, 1)))
        with pytest.raises(LedgerUnavailable):
            await w.ledger.accounts(w.household_id, 5)
    assert run(db_url, scenario).seen == []


def test_with_nothing_wired_the_ledger_is_the_null_object() -> None:
    services.clear()
    ledger = services.get(Ledger)
    assert isinstance(ledger, NullLedger)

    async def go() -> None:
        assert await ledger.connected(1) is False
        for read in READS.values():
            with pytest.raises(NotConnected):
                await read(ledger, 1)
    asyncio.run(go())


def test_ledger_failed_names_its_reason() -> None:
    assert "refused" in repr(LedgerFailed("refused")) + str(LedgerFailed("refused"))
