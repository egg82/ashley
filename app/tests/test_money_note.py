"""`money_note` end to end through `MoneyTools` against the fake Sure: a note on one transaction is an `asks` change
beside `money_categorise`, offered where it is and not in a reads-only turn; it writes only the note, once, and the
next read of the transaction carries it; wrong arguments change nothing; what the person is shown is the transaction by
date, amount and account, the note, and whether it replaces one, never the transaction's name or merchant."""

import asyncio
import json
from collections.abc import Iterator

import pytest
from ashley import logs, services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult
from ashley.ledger.ledger import Ledger
from ashley.sure.client import Sure
from ashley.tools import money_config
from ashley.tools.money import MoneyTools
from ashley.tools.reading import Reading
from ashley.tools.tools import Unshown
from money_support import FakeSure, HeldConnections, transaction

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

HOME = 10
CONFIG = money_config.load()
NOTE = "money_note"
T1 = "d1b2c3d4-0000-4000-8000-000000000001"
T2 = "d1b2c3d4-0000-4000-8000-000000000002"
PAYEE = "Payee Planted Words"


@pytest.fixture
def sure() -> Iterator[FakeSure]:
    held = HeldConnections()
    held.connect(HOME)
    services.register(Connections, held)
    fake = FakeSure()
    rows = fake.answers["/api/v1/transactions"]
    assert isinstance(rows, dict)
    rows["transactions"] = [{**transaction(PAYEE, "$1.00", "2026-10-30"), "id": T1},
                            {**transaction(PAYEE, "$7.50", "2026-10-28"), "id": T2, "notes": "an older note"}]
    services.register(Sure, fake.client())
    yield fake


def call(name: str, **arguments: object) -> ToolResult:
    return asyncio.run(MoneyTools(HOME, CONFIG).call(ToolCall("c1", name, arguments)))


def shown(**arguments: object) -> str | None:
    return asyncio.run(MoneyTools(HOME, CONFIG).shown(ToolCall("c1", NOTE, arguments)))


def test_it_is_an_asks_change_a_reads_only_turn_is_not_offered(sure: FakeSure) -> None:
    offered = asyncio.run(MoneyTools(HOME, CONFIG).catalogue()).specs
    assert [(s.name, s.outside, s.tier) for s in offered if s.name == NOTE] == [(NOTE, False, "asks")]
    reading = asyncio.run(Reading(MoneyTools(HOME, CONFIG)).catalogue()).specs
    assert NOTE not in [s.name for s in reading]


def test_the_note_is_put_alone_and_the_next_read_carries_it(sure: FakeSure) -> None:
    got = call(NOTE, transaction_id=T1, note="split with Sam")
    assert not got.is_error and json.loads(got.content) == {"set": 1}
    assert sure.written == [(f"/api/v1/transactions/{T1}", {"transaction": {"notes": "split with Sam"}})]
    assert asyncio.run(_noted(T1)) is True


async def _noted(transaction_id: str) -> bool:
    got = await services.get(Ledger).entry(HOME, transaction_id)
    assert got is not None
    return got.noted


def test_a_transaction_sure_does_not_have_is_named_not_found(sure: FakeSure) -> None:
    missing = "d1b2c3d4-0000-4000-8000-0000000000ff"
    got = json.loads(call(NOTE, transaction_id=missing, note="x").content)
    assert got == {"set": 0, "not_found": [missing]}


def test_a_split_part_is_named_rejected(sure: FakeSure) -> None:
    sure.split_parts.add(T1)
    assert json.loads(call(NOTE, transaction_id=T1, note="x").content) == {"set": 0, "rejected": [T1]}


@pytest.mark.parametrize("arguments", [
    {"note": "x"},
    {"transaction_id": T1},
    {"transaction_id": "t-Shop 0", "note": "x"},
    {"transaction_id": [T1], "note": "x"},
    {"transaction_id": T1, "note": ""},
    {"transaction_id": T1, "note": "   "},
    {"transaction_id": T1, "note": 5},
    {"transaction_id": T1, "note": "x" * (CONFIG.note_chars + 1)},
])
def test_wrong_arguments_ask_sure_nothing(sure: FakeSure, arguments: dict[str, object]) -> None:
    got = call(NOTE, **arguments)
    assert got.is_error and sure.seen == [] and sure.written == []


def test_the_longest_note_allowed_is_put(sure: FakeSure) -> None:
    assert not call(NOTE, transaction_id=T1, note="x" * CONFIG.note_chars).is_error


def test_a_key_that_may_only_read_says_so(sure: FakeSure) -> None:
    sure.reads_only = True
    got = call(NOTE, transaction_id=T1, note="x")
    assert got.is_error and "may write" in got.content


def test_the_person_is_shown_the_transaction_and_the_note_never_its_name(sure: FakeSure) -> None:
    line = shown(transaction_id=T1, note="split with Sam")
    assert line == 'Note on 2026-10-30, $1.00 in Checking: "split with Sam"'
    assert PAYEE not in (line or "") and "Corner Grocer" not in (line or "")
    assert sure.written == []


def test_the_person_is_told_when_it_replaces_a_note_without_being_shown_the_old_one(sure: FakeSure) -> None:
    line = shown(transaction_id=T2, note="new words")
    assert line == 'Note on 2026-10-28, $7.50 in Checking, replacing its note: "new words"'
    assert "an older note" not in (line or "")


def test_a_note_on_nothing_the_household_has_cannot_be_shown(sure: FakeSure) -> None:
    with pytest.raises(Unshown, match="money_transactions"):
        shown(transaction_id="d1b2c3d4-0000-4000-8000-0000000000ff", note="x")
    with pytest.raises(Unshown):
        shown(transaction_id=T1, note="")


def test_the_log_carries_the_tool_and_no_words(sure: FakeSure, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    call(NOTE, transaction_id=T1, note="split with Sam")
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if "event=tools.call" in ln)
    assert f"tool={NOTE} " in line and "rows=1" in line and "Sam" not in out
