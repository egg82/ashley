"""A read Sure answered marks the household's connection answered (`checked_at` moves); one that failed does not."""

from collections.abc import Awaitable, Callable
from datetime import datetime

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.ledger.ledger import Ledger
from ashley.ledger.model import LedgerFailed, NotConnected, TransactionQuery
from ledger_blind_support import AnswerLost, FakeSure, World, other_household, run
from connection_legacy_support import put_of


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

Read = Callable[[Ledger, int], Awaitable[object]]
READS: dict[str, Read] = {
    "accounts": lambda ledger, h: ledger.accounts(h, 5),
    "categories": lambda ledger, h: ledger.categories(h, 5),
    "net_worth": lambda ledger, h: ledger.net_worth(h),
    "transactions": lambda ledger, h: ledger.transactions(h, TransactionQuery(per_page=5)),
}


def moved(before: object, after: object) -> bool:
    assert isinstance(before, datetime) and isinstance(after, datetime)
    return after > before


@pytest.mark.parametrize("name", READS)
def test_a_successful_read_moves_checked_at(db_url: str, name: str) -> None:
    async def scenario(w: World) -> None:
        before = w.age()
        await READS[name](w.ledger, w.household_id)
        assert moved(before, w.checked_at())
    run(db_url, scenario)


@pytest.mark.parametrize("name", READS)
@pytest.mark.parametrize("fake", [FakeSure(key="wrong"), FakeSure(down=True), FakeSure(status=500),
                                  FakeSure(raw=b"<html>")], ids=["refused", "down", "500", "html"])
def test_a_failed_read_leaves_checked_at_alone(db_url: str, name: str, fake: FakeSure) -> None:
    async def scenario(w: World) -> None:
        before = w.age()
        with pytest.raises(LedgerFailed):
            await READS[name](w.ledger, w.household_id)
        assert w.checked_at() == before
    run(db_url, scenario, fake)


def test_a_read_of_the_wrong_shape_does_not_move_it(db_url: str) -> None:
    fake = FakeSure()
    fake.answers["/api/v1/accounts"] = {"accounts": 3}

    async def scenario(w: World) -> None:
        before = w.age()
        with pytest.raises(LedgerFailed):
            await w.ledger.accounts(w.household_id, 5)
        assert w.checked_at() == before
    run(db_url, scenario, fake)


def test_a_read_that_cannot_record_its_answer_still_returns_what_was_read(db_url: str) -> None:
    async def scenario(w: World) -> None:
        services.register(Connections, AnswerLost(w.connections))
        assert len((await w.ledger.accounts(w.household_id, 5)).rows) == 2
    run(db_url, scenario)


def test_only_the_households_own_connection_moves(db_url: str) -> None:
    async def scenario(w: World) -> None:
        second, person = other_household(db_url, "second")
        await put_of(w.connections, second, "sure", "https://money.test", "the-households-test-key", person)
        mine, theirs = w.age(), w.age(second)
        await w.ledger.accounts(second, 5)
        assert w.checked_at() == mine and moved(theirs, w.checked_at(second))
    run(db_url, scenario)


def test_a_household_with_no_connection_has_nothing_to_move(db_url: str) -> None:
    async def scenario(w: World) -> None:
        with pytest.raises(NotConnected):
            await w.ledger.accounts(w.household_id, 5)
    run(db_url, scenario, connect=False)
