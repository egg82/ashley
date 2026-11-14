"""`money_categorise` behind `Outside`, as a person's turn wraps her money tools: it is an `asks` change, so every call is
held for the person's OK, tainted turn or not, and Sure is only read (to show it) until they agree; what they are shown
is each transaction's date, amount and account, the category it leaves and the one it goes to, never its name or
merchant; their later, untainted turn agreeing with `carry_out`, or a tap on Agree, sets it with the stored arguments;
a judge that would clear it is never asked; a change that cannot be shown is not held; a declined (never agreed) or
expired proposal writes nothing."""

from collections.abc import Iterator, Sequence

import psycopg
import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.proposals import ProposalRefused, Proposals
from ashley.sure.client import Sure
from ashley.tools import money_config
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.money import MoneyTools
from ashley.tools.money_specs import CATEGORISE, TRANSACTIONS
from ashley.tools.outside import CARRY_OUT, Outside, Standing
from money_support import GROCERIES, FakeSure, HeldConnections, transaction
from outside_ask_support import CONVERSATION, HOUSEHOLD, STANDING, TURN, Memory, Tainted, run, store

pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

T1 = "c1b2c3d4-0000-4000-8000-000000000001"
T2 = "c1b2c3d4-0000-4000-8000-000000000002"
DINING: dict[str, object] = {"id": "9d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e7", "name": "Dining", "color": "#f00",
                             "icon": "fork"}
ASK = ToolCall("c2", CATEGORISE, {"transaction_ids": [T1, T2], "category_id": GROCERIES})
PAYEE, MERCHANT = "Payee Planted Words", "Corner Grocer"


def put(ids: Sequence[str]) -> list[tuple[str, object]]:
    return [(f"/api/v1/transactions/{t}", {"transaction": {"category_id": GROCERIES}}) for t in ids]


def fake_sure(household_id: int) -> FakeSure:
    held = HeldConnections()
    held.connect(household_id)
    services.register(Connections, held)
    fake = FakeSure()
    rows = fake.answers["/api/v1/transactions"]
    assert isinstance(rows, dict)
    rows["transactions"] = [{**transaction(PAYEE, "$1.00", "2026-10-30", DINING), "id": T1},
                            {**transaction(PAYEE, "$7.50", "2026-10-28"), "id": T2}]
    services.register(Sure, fake.client())
    return fake


@pytest.fixture
def sure() -> Iterator[FakeSure]:
    services.register(Proposals, Memory())
    yield fake_sure(HOUSEHOLD)


class Clears(ActionJudge):
    def __init__(self) -> None:
        self.asked = 0

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked += 1
        return Verdict("run", "asked_directly", "They asked for it.")


async def words() -> Sequence[str]:
    return ("put those under groceries",)


def turn(turn_id: int, standing: Standing | None = STANDING, household_id: int = HOUSEHOLD) -> Outside:
    return Outside(MoneyTools(household_id, money_config.load()), standing, (CONVERSATION, turn_id), Tainted(), None,
                   None, words)


def test_a_turn_that_read_nothing_from_outside_holds_it_and_shows_what_would_change(sure: FakeSure) -> None:
    async def go() -> None:
        first = turn(TURN)
        await first.catalogue()
        got = await first.call(ASK)
        assert not got.is_error and "held" in got.content and first.tainted is None and first.held == 1
        assert sure.written == []
        receipts = await first.receipts()
        assert receipts is not None and receipts.proposal_id is not None and len(receipts.held) == 1
        shown = receipts.held[0].detail
        assert shown == ("Move 2 transactions to Food / Groceries: 2026-10-30, $1.00 in Checking, from Dining; "
                         "2026-10-28, $7.50 in Checking, from no category")
        assert shown is not None and PAYEE not in shown and MERCHANT not in shown

    run(go())


def test_agreeing_in_a_later_turn_sets_it_with_the_stored_arguments(sure: FakeSure) -> None:
    async def go() -> None:
        await turn(TURN).call(ASK)
        later = turn(TURN + 1)
        assert CARRY_OUT in [s.name for s in (await later.catalogue()).specs]
        assert sure.written == []
        done = await later.call(ToolCall("c3", CARRY_OUT, {}))
        assert not done.is_error
        assert sure.written == put([T1, T2])

    run(go())


def test_after_reading_transactions_it_is_held_without_asking_the_judge(sure: FakeSure) -> None:
    judge = Clears()
    services.register(ActionJudge, judge)

    async def go() -> None:
        first = turn(TURN)
        await first.call(ToolCall("c1", TRANSACTIONS, {}))
        assert first.tainted == TRANSACTIONS
        got = await first.call(ASK)
        assert not got.is_error and first.held == 1 and judge.asked == 0
        assert sure.written == []

    run(go())


def test_the_turn_that_held_it_cannot_agree_to_it(sure: FakeSure) -> None:
    async def go() -> None:
        first = turn(TURN)
        await first.call(ASK)
        refused = await first.call(ToolCall("c3", CARRY_OUT, {}))
        assert refused.is_error and sure.written == []

    run(go())


@pytest.mark.parametrize(("arguments", "told"), [
    ({"transaction_ids": [T1, "c1b2c3d4-0000-4000-8000-0000000000ff"], "category_id": GROCERIES}, "money_transactions"),
    ({"transaction_ids": [T1], "category_id": "9d1e2f3a-4b5c-4d6e-8f70-0000000000ff"}, "money_categories lists"),
    ({"transaction_ids": [T1], "category_id": "groceries"}, "an id as money_categories gives it"),
])
def test_a_change_that_cannot_be_shown_is_not_held(sure: FakeSure, arguments: dict[str, object], told: str) -> None:
    async def go() -> None:
        first = turn(TURN)
        got = await first.call(ToolCall("c2", CATEGORISE, arguments))
        assert got.is_error and told in got.content and first.held == 0
        assert await services.get(Proposals).pending(STANDING.speaker_id, CONVERSATION, OUTSIDE) is None
        assert sure.written == []

    run(go())


def test_sure_down_while_showing_holds_nothing(sure: FakeSure) -> None:
    sure.status = 503

    async def go() -> None:
        got = await turn(TURN).call(ASK)
        assert got.is_error and "could not be read" in got.content
        assert await services.get(Proposals).pending(STANDING.speaker_id, CONVERSATION, OUTSIDE) is None
        assert sure.written == []

    run(go())


@pytest.mark.parametrize("standing", [None, Standing(HOUSEHOLD, 7, private=False, agreeing=True)])
def test_where_nobody_can_be_asked_it_is_refused_and_not_made(sure: FakeSure, standing: Standing | None) -> None:
    async def go() -> None:
        got = await turn(TURN, standing).call(ASK)
        assert got.is_error and sure.written == []

    run(go())


def test_a_tap_agrees_and_a_proposal_never_agreed_or_expired_writes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            fake = fake_sure(s.house)
            alana = Standing(s.house, s.alana, private=True, agreeing=True)
            holding = turn(TURN, alana, s.house)
            await holding.catalogue()
            await holding.call(ASK)
            receipts = await holding.receipts()
            assert receipts is not None and receipts.proposal_id is not None
            declined = turn(TURN + 1, alana, s.house)
            await declined.catalogue()
            assert fake.written == []
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("UPDATE proposals SET created_at = created_at - interval '1 day'")
            with pytest.raises(ProposalRefused) as lapsed:
                await turn(TURN + 2, alana, s.house).agreed("agreed", receipts.proposal_id)
            assert lapsed.value.reason == "expired" and fake.written == []

            asked_again = turn(TURN + 3, alana, s.house)
            await asked_again.catalogue()
            await asked_again.call(ASK)
            again = await asked_again.receipts()
            assert again is not None and again.proposal_id is not None
            outcome = await turn(TURN + 4, alana, s.house).agreed("agreed", again.proposal_id)
            assert [a.status for a in outcome] == ["ran"] and fake.written == put([T1, T2])

    run(go())
