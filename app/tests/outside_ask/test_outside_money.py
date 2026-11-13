"""`money_categorise` behind `Outside`, as a person's turn wraps her money tools: once the turn has read transactions
(payee text from outside) a categorisation the judge does not clear is held for the person's OK and Sure is not
written; the person's later, untainted turn agreeing with `carry_out` sets it with the stored arguments; a judge that
clears it from the person's own words lets it run; a turn that read nothing from outside sets it at once."""

from collections.abc import Iterator, Sequence

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall
from ashley.sure.client import Sure
from ashley.tools import money_config
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.money import MoneyTools
from ashley.tools.money_specs import CATEGORISE, TRANSACTIONS
from ashley.tools.outside import CARRY_OUT, Outside
from money_support import GROCERIES, FakeSure, HeldConnections, transaction
from outside_ask_support import CONVERSATION, HOUSEHOLD, STANDING, TURN, Memory, Tainted, run
from ashley.senses.proposals import Proposals

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

T1 = "c1b2c3d4-0000-4000-8000-000000000001"
ASK = ToolCall("c2", CATEGORISE, {"transaction_ids": [T1], "category_id": GROCERIES})


@pytest.fixture
def sure() -> Iterator[FakeSure]:
    held = HeldConnections()
    held.connect(HOUSEHOLD)
    services.register(Connections, held)
    services.register(Proposals, Memory())
    fake = FakeSure()
    rows = fake.answers["/api/v1/transactions"]
    assert isinstance(rows, dict)
    rows["transactions"] = [{**transaction("Shop", "$1.00", "2026-10-30"), "id": T1}]
    services.register(Sure, fake.client())
    yield fake


class Clears(ActionJudge):
    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        return Verdict("run", "asked_directly", "They asked for it.")


async def words() -> Sequence[str]:
    return ("put the shop one under groceries",)


def turn(turn_id: int) -> Outside:
    return Outside(MoneyTools(HOUSEHOLD, money_config.load()), STANDING, (CONVERSATION, turn_id), Tainted(), None,
                   None, words)


def test_after_reading_transactions_it_is_held_and_agreeing_later_sets_it(sure: FakeSure) -> None:
    async def go() -> None:
        first = turn(TURN)
        await first.call(ToolCall("c1", TRANSACTIONS, {}))
        assert first.tainted == TRANSACTIONS
        got = await first.call(ASK)
        assert not got.is_error and "held" in got.content and first.held == 1
        assert sure.written == []
        later = turn(TURN + 1)
        assert CARRY_OUT in [s.name for s in (await later.catalogue()).specs]
        done = await later.call(ToolCall("c3", CARRY_OUT, {}))
        assert not done.is_error
        assert sure.written == [(f"/api/v1/transactions/{T1}", {"transaction": {"category_id": GROCERIES}})]

    run(go())


def test_the_turn_that_held_it_cannot_agree_to_it(sure: FakeSure) -> None:
    async def go() -> None:
        first = turn(TURN)
        await first.call(ToolCall("c1", TRANSACTIONS, {}))
        await first.call(ASK)
        refused = await first.call(ToolCall("c3", CARRY_OUT, {}))
        assert refused.is_error and sure.written == []

    run(go())


def test_a_judge_that_clears_it_from_the_persons_words_lets_it_run(sure: FakeSure) -> None:
    services.register(ActionJudge, Clears())

    async def go() -> None:
        first = turn(TURN)
        await first.call(ToolCall("c1", TRANSACTIONS, {}))
        got = await first.call(ASK)
        assert not got.is_error and first.held == 0
        assert [p for p, _ in sure.written] == [f"/api/v1/transactions/{T1}"]

    run(go())


def test_a_turn_that_read_nothing_from_outside_sets_it_at_once(sure: FakeSure) -> None:
    async def go() -> None:
        first = turn(TURN)
        got = await first.call(ASK)
        assert not got.is_error and first.tainted is None and first.held == 0
        assert [p for p, _ in sure.written] == [f"/api/v1/transactions/{T1}"]

    run(go())
