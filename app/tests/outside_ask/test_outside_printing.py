"""`printing_queue` behind `Outside` and the trust seam, as a person's turn wraps her tools. It is `asks_if_tainted`: a
person asking for it is their yes and it queues straight away; a turn that has read outside words holds it for their OK
without asking a judge, and Bambuddy is only read (to show it) until they agree; a turn nobody asked for goes by their
"what she may just do" setting, whose `printing` kind is `act` unless they stored `offer`, and what it queued there is
recorded with the Undo that cancels it. What a held print shows is the file's id, type, time and weight, the printer by
the household's name and each slot against what the printer says is in it, never the file's name; a later, untainted
turn agreeing with `carry_out` queues it, staged, with the stored arguments; a print that cannot be shown is not held."""

from collections.abc import Iterator, Sequence

import pytest
from ashley import services
from ashley.bambuddy.client import Bambuddy
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall
from ashley.printing.printing import Printing
from ashley.senses.outside_record import Cause, OutsideRecord
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.proposals import Proposals
from ashley.tools import printing_config
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.outside import CARRY_OUT, Outside, Standing
from ashley.tools.printing_queue import PrintQueueTools
from ashley.tools.printing_queue_specs import QUEUE
from ashley.tools.tools import Tools
from ashley.tools.trusting import Trusting
from ashley.trust.kinds import Value
from ashley.trust.trust import StoredTrust, Trust, TrustUnavailable
from ashley.undo import Undo
from bambuddy_support import FakeBambuddy, held
from outside_ask_support import CONVERSATION, HOUSEHOLD, SPEAKER, STANDING, TURN, Memory, Tainted, run
from outside_record_support import MemoryRecord

ASK = ToolCall("c2", QUEUE, {"file_id": "2", "printer_id": "1", "slots": [{"need": 2, "unit": 1, "slot": 2}]})
QUEUED = [{"printer_id": 1, "library_file_id": 2, "manual_start": True, "ams_mapping": [-1, 1]}]
UNASKED = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=False, unasked=True, cause=Cause("bench", 3))


class Told(Trust):
    """Answers `values` as the person's stored choices, or cannot be read."""

    def __init__(self, values: dict[str, Value] | None) -> None:
        self.values = values

    async def stored(self, household_id: int, person_id: int) -> StoredTrust:
        if self.values is None:
            raise TrustUnavailable("down")
        return StoredTrust(1, self.values)


@pytest.fixture
def bambuddy() -> Iterator[FakeBambuddy]:
    services.register(Proposals, Memory())
    services.register(OutsideRecord, MemoryRecord())
    fake = FakeBambuddy()
    services.register(Connections, held(HOUSEHOLD))
    services.register(Bambuddy, fake.client())
    services.register(Printing, BambuddyPrinting())
    yield fake
    services.unregister(Trust)


class Clears(ActionJudge):
    def __init__(self) -> None:
        self.asked = 0

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked += 1
        return Verdict("run", "asked_directly", "They asked for it.")


async def words() -> Sequence[str]:
    return ("put the phone stand in the queue",)


def turn(turn_id: int, standing: Standing | None = STANDING, tainted: str | None = None,
         told: Trust | None = None) -> Outside:
    source: Tools = PrintQueueTools(HOUSEHOLD, printing_config.load())
    if told is not None:
        services.register(Trust, told)
        source = Trusting(source, HOUSEHOLD, SPEAKER)
    return Outside(source, standing, (CONVERSATION, turn_id), Tainted(), tainted, None, words)


def recorded() -> list[tuple[str, Cause | None, Undo | None]]:
    record = services.get(OutsideRecord)
    assert isinstance(record, MemoryRecord)
    return [(a.tool, a.cause, a.undo) for a in record.actions]


def test_a_person_asking_for_it_queues_it_straight_away(bambuddy: FakeBambuddy) -> None:
    async def go() -> None:
        asked = turn(TURN)
        await asked.catalogue()
        got = await asked.call(ASK)
        assert not got.is_error and '"queued"' in got.content and asked.held == 0
        assert bambuddy.queued == QUEUED and await asked.receipts() is None
        assert recorded() == [], "a person's own untainted turn records nothing"

    run(go())


@pytest.mark.parametrize("told", [Told({}), Told({"printing": "act"})], ids=["unset", "stored_act"])
def test_a_turn_nobody_asked_for_queues_it_and_records_the_cancel(bambuddy: FakeBambuddy, told: Told) -> None:
    async def go() -> None:
        unasked = turn(TURN, UNASKED, told=told)
        await unasked.catalogue()
        got = await unasked.call(ASK)
        assert not got.is_error and unasked.held == 0 and bambuddy.queued == QUEUED
        assert recorded() == [(QUEUE, Cause("bench", 3), Undo("print_cancel", "101"))]

    run(go())


@pytest.mark.parametrize("told", [Told({"printing": "offer"}), Told(None)], ids=["offer", "unreadable"])
def test_a_turn_nobody_asked_for_holds_it_when_they_said_offer_or_it_cannot_tell(bambuddy: FakeBambuddy,
                                                                                told: Told) -> None:
    async def go() -> None:
        unasked = turn(TURN, UNASKED, told=told)
        await unasked.catalogue()
        got = await unasked.call(ASK)
        assert not got.is_error and "held" in got.content and unasked.held == 1
        assert bambuddy.queued == [] and recorded() == []
        later = turn(TURN + 1)
        done = await later.call(ToolCall("c3", CARRY_OUT, {}))
        assert not done.is_error and bambuddy.queued == QUEUED

    run(go())


def test_a_tainted_turn_holds_it_shows_it_and_queues_only_when_they_agree(bambuddy: FakeBambuddy) -> None:
    async def go() -> None:
        first = turn(TURN, tainted="printing_files")
        await first.catalogue()
        got = await first.call(ASK)
        assert not got.is_error and "held" in got.content and first.held == 1
        receipts = await first.receipts()
        assert receipts is not None and receipts.proposal_id is not None
        shown = receipts.held[0].detail
        assert shown == ("Queue library file 2 (3mf, 1 h 0 min, 12.5 g) on Shed X1C; filament 2 from AMS 1 slot 2 (PETG). "
                         "It waits, staged, until someone starts it in Bambuddy")
        assert "Phone stand" not in shown and bambuddy.queued == []
        assert (await first.call(ToolCall("c3", CARRY_OUT, {}))).is_error, "the turn that held it cannot agree to it"
        later = turn(TURN + 1)
        assert CARRY_OUT in [s.name for s in (await later.catalogue()).specs]
        done = await later.call(ToolCall("c4", CARRY_OUT, {}))
        assert not done.is_error and bambuddy.queued == QUEUED

    run(go())


@pytest.mark.parametrize("told", [None, Told({"printing": "act"})], ids=["asked", "unasked_act"])
def test_it_is_held_without_asking_the_judge_in_any_tainted_turn(bambuddy: FakeBambuddy, told: Told | None) -> None:
    judge = Clears()
    services.register(ActionJudge, judge)

    async def go() -> None:
        first = turn(TURN, STANDING if told is None else UNASKED, tainted="printing_files", told=told)
        got = await first.call(ASK)
        assert not got.is_error and first.held == 1 and judge.asked == 0 and bambuddy.queued == []

    run(go())


@pytest.mark.parametrize(("arguments", "told"), [
    ({"file_id": "99", "printer_id": "1"}, "printing_files lists"),
    ({"file_id": "2", "printer_id": "7"}, "printing_printers lists"),
    ({"file_id": "2", "printer_id": "1", "slots": [{"need": 1, "unit": 3, "slot": 1}]}, "printing_ams and printing_needs"),
    ({"file_id": "x", "printer_id": "1"}, "an id as printing_files gives it"),
])
def test_a_print_that_cannot_be_shown_is_not_held(bambuddy: FakeBambuddy, arguments: dict[str, object], told: str) -> None:
    async def go() -> None:
        first = turn(TURN, tainted="printing_files")
        got = await first.call(ToolCall("c2", QUEUE, arguments))
        assert got.is_error and told in got.content and first.held == 0
        assert await services.get(Proposals).pending(STANDING.speaker_id, CONVERSATION, OUTSIDE) is None
        assert bambuddy.queued == []

    run(go())


def test_bambuddy_down_while_showing_holds_nothing(bambuddy: FakeBambuddy) -> None:
    bambuddy.status = 503

    async def go() -> None:
        got = await turn(TURN, tainted="printing_files").call(ASK)
        assert got.is_error and "could not be read" in got.content and bambuddy.queued == []

    run(go())


@pytest.mark.parametrize("standing", [None, Standing(HOUSEHOLD, 7, private=False, agreeing=True)])
def test_where_nobody_can_be_asked_a_tainted_one_is_refused_and_not_queued(bambuddy: FakeBambuddy,
                                                                          standing: Standing | None) -> None:
    async def go() -> None:
        got = await turn(TURN, standing, tainted="printing_files").call(ASK)
        assert got.is_error and bambuddy.queued == []

    run(go())
