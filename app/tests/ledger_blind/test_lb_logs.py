"""Reads log ids and counts, never amounts, payees, names, searches or the key."""

import pytest
from ashley import logs
from ashley.ledger.model import LedgerFailed, TransactionQuery
from ledger_blind_support import AMOUNT, KEY, PAYEE, FakeSure, World, run


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")

SEARCH = "zebra-crossing-search-words"
PRIVATE = [PAYEE, AMOUNT, "Checking", "Visa", "Groceries", "Rent", "Food", "$1,234.56", "-$300.00", "$934.56",
           "1234.56", "2026-10-30", KEY, SEARCH]


async def every_read(w: World) -> None:
    await w.ledger.accounts(w.household_id, 5)
    await w.ledger.categories(w.household_id, 5)
    await w.ledger.net_worth(w.household_id)
    await w.ledger.transactions(w.household_id, TransactionQuery(per_page=5, search=SEARCH))


def test_answered_reads_log_none_of_the_money(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    run(db_url, every_read)
    out = capsys.readouterr()
    text = out.out + out.err
    assert "event=sure.get" in text
    for private in PRIVATE:
        assert private not in text, private


@pytest.mark.parametrize("fake", [FakeSure(key="wrong"), FakeSure(down=True), FakeSure(raw=b"<html>" + PAYEE.encode())],
                         ids=["refused", "down", "html"])
def test_failed_reads_log_none_of_the_money_either(db_url: str, capsys: pytest.CaptureFixture[str],
                                                   fake: FakeSure) -> None:
    logs.setup()
    capsys.readouterr()

    async def scenario(w: World) -> None:
        for call in (w.ledger.accounts(w.household_id, 5),
                     w.ledger.transactions(w.household_id, TransactionQuery(per_page=5, search=SEARCH))):
            with pytest.raises(LedgerFailed):
                await call
    run(db_url, scenario, fake)
    out = capsys.readouterr()
    text = out.out + out.err
    for private in PRIVATE:
        assert private not in text, private
