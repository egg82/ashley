"""`printing_queue` behind `Outside`, as a person's turn wraps her tools: an `asks` change, so every call is held for the
person's OK, tainted turn or not, and Bambuddy is only read (to show it) until they agree; what they are shown is the
file's id, type, time and weight, the printer by the household's name and each slot against what the printer says is in it,
never the file's name; a later, untainted turn agreeing with `carry_out` queues it, staged, with the stored arguments;
a judge that would clear it is never asked; a print that cannot be shown is not held; one never agreed queues nothing."""

from collections.abc import Iterator, Sequence

import pytest
from ashley import services
from ashley.bambuddy.client import Bambuddy
from ashley.bambuddy.printing import BambuddyPrinting
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall
from ashley.printing.printing import Printing
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.proposals import Proposals
from ashley.tools import printing_config
from ashley.tools.action_judge import ActionJudge, Verdict, View
from ashley.tools.outside import CARRY_OUT, Outside, Standing
from ashley.tools.printing_queue import PrintQueueTools
from ashley.tools.printing_queue_specs import QUEUE
from bambuddy_support import FakeBambuddy, held
from outside_ask_support import CONVERSATION, HOUSEHOLD, STANDING, TURN, Memory, Tainted, run

ASK = ToolCall("c2", QUEUE, {"file_id": "2", "printer_id": "1", "slots": [{"need": 2, "unit": 1, "slot": 2}]})
QUEUED = [{"printer_id": 1, "library_file_id": 2, "manual_start": True, "ams_mapping": [-1, 1]}]


@pytest.fixture
def bambuddy() -> Iterator[FakeBambuddy]:
    services.register(Proposals, Memory())
    fake = FakeBambuddy()
    services.register(Connections, held(HOUSEHOLD))
    services.register(Bambuddy, fake.client())
    services.register(Printing, BambuddyPrinting())
    yield fake


class Clears(ActionJudge):
    def __init__(self) -> None:
        self.asked = 0

    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        self.asked += 1
        return Verdict("run", "asked_directly", "They asked for it.")


async def words() -> Sequence[str]:
    return ("put the phone stand in the queue",)


def turn(turn_id: int, standing: Standing | None = STANDING, tainted: str | None = None) -> Outside:
    return Outside(PrintQueueTools(HOUSEHOLD, printing_config.load()), standing, (CONVERSATION, turn_id), Tainted(),
                   tainted, None, words)


def test_a_call_is_held_and_shown_and_nothing_is_queued_until_they_agree(bambuddy: FakeBambuddy) -> None:
    async def go() -> None:
        first = turn(TURN)
        await first.catalogue()
        got = await first.call(ASK)
        assert not got.is_error and "held" in got.content and first.held == 1
        receipts = await first.receipts()
        assert receipts is not None and receipts.proposal_id is not None
        shown = receipts.held[0].detail
        assert shown == ("Queue library file 2 (3mf, 1 h 0 min, 12.5 g) on Shed X1C; filament 2 from AMS 1 slot 2 (PETG). "
                         "It waits, staged, until someone starts it in Bambuddy")
        assert "Phone stand" not in shown and bambuddy.queued == []
        later = turn(TURN + 1)
        assert CARRY_OUT in [s.name for s in (await later.catalogue()).specs]
        done = await later.call(ToolCall("c3", CARRY_OUT, {}))
        assert not done.is_error and bambuddy.queued == QUEUED

    run(go())


def test_it_is_held_without_asking_the_judge_even_in_a_tainted_turn(bambuddy: FakeBambuddy) -> None:
    judge = Clears()
    services.register(ActionJudge, judge)

    async def go() -> None:
        first = turn(TURN, tainted="printing_files")
        got = await first.call(ASK)
        assert not got.is_error and first.held == 1 and judge.asked == 0 and bambuddy.queued == []

    run(go())


def test_the_turn_that_held_it_cannot_agree_to_it(bambuddy: FakeBambuddy) -> None:
    async def go() -> None:
        first = turn(TURN)
        await first.call(ASK)
        refused = await first.call(ToolCall("c3", CARRY_OUT, {}))
        assert refused.is_error and bambuddy.queued == []

    run(go())


@pytest.mark.parametrize(("arguments", "told"), [
    ({"file_id": "99", "printer_id": "1"}, "printing_files lists"),
    ({"file_id": "2", "printer_id": "7"}, "printing_printers lists"),
    ({"file_id": "2", "printer_id": "1", "slots": [{"need": 1, "unit": 3, "slot": 1}]}, "printing_ams and printing_needs"),
    ({"file_id": "x", "printer_id": "1"}, "an id as printing_files gives it"),
])
def test_a_print_that_cannot_be_shown_is_not_held(bambuddy: FakeBambuddy, arguments: dict[str, object], told: str) -> None:
    async def go() -> None:
        first = turn(TURN)
        got = await first.call(ToolCall("c2", QUEUE, arguments))
        assert got.is_error and told in got.content and first.held == 0
        assert await services.get(Proposals).pending(STANDING.speaker_id, CONVERSATION, OUTSIDE) is None
        assert bambuddy.queued == []

    run(go())


def test_bambuddy_down_while_showing_holds_nothing(bambuddy: FakeBambuddy) -> None:
    bambuddy.status = 503

    async def go() -> None:
        got = await turn(TURN).call(ASK)
        assert got.is_error and "could not be read" in got.content and bambuddy.queued == []

    run(go())


@pytest.mark.parametrize("standing", [None, Standing(HOUSEHOLD, 7, private=False, agreeing=True)])
def test_where_nobody_can_be_asked_it_is_refused_and_not_queued(bambuddy: FakeBambuddy, standing: Standing | None) -> None:
    async def go() -> None:
        got = await turn(TURN, standing).call(ASK)
        assert got.is_error and bambuddy.queued == []

    run(go())
