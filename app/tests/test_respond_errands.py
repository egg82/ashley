"""Errands in `respond`: a kept `Reply.owed` stores one errand for the person turn; it is kept only for a known speaker
and a source this turn's catalogue found out of reach, else dropped and counted; finished errands are shown to a known
speaker under `# While they were away` and marked told once her turn is stored, the answer's for a held reply."""

import asyncio
from collections.abc import Collection, Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.channels.model import Inbound
from ashley.errands.config import CONFIG
from ashley.errands.errands import Errands, ErrandsUnavailable, NullErrands
from ashley.errands.model import Done
from ashley.inference.model import ToolSpec
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue, Tools
from later_support import Logged, until
from respond_support import ALANA, Fakes, FakeTools, calls, inbound, wired as wired

OWING = Reply(spoken="I can't just now.", text="I can't just now.", owed="house")
PLAIN = OWING.model_copy(update={"owed": None})
DONE = Done(5, ALANA.id, "house", "Added milk to the shopping list.", "shared", datetime(2026, 10, 24, 15, tzinfo=UTC))


@dataclass
class FakeErrands(NullErrands):
    waiting: tuple[Done, ...] = ()
    down: bool = False
    owed: list[tuple[int, int, int, int, str]] = field(default_factory=list[tuple[int, int, int, int, str]])
    asked: list[tuple[int, int, bool]] = field(default_factory=list[tuple[int, int, bool]])
    told_ids: list[list[int]] = field(default_factory=list[list[int]])

    async def owe(self, household_id: int, asker_id: int, conversation_id: int, turn_id: int, source: str) -> int:
        self.owed.append((household_id, asker_id, conversation_id, turn_id, source))
        return len(self.owed)

    async def untold(self, hearer: int, limit: int, owner_only: bool = True) -> tuple[Done, ...]:
        self.asked.append((hearer, limit, owner_only))
        return self.waiting

    async def told(self, errand_ids: Collection[int]) -> None:
        if self.down:
            raise ErrandsUnavailable("down")
        self.told_ids.append(list(errand_ids))


@dataclass
class OutTools(FakeTools):
    out: tuple[str, ...] = ("house",)

    async def catalogue(self) -> Catalogue:
        found = await super().catalogue()
        return replace(found, unreachable=self.out)


@pytest.fixture
def logged(capsys: pytest.CaptureFixture[str]) -> Logged:
    return Logged(capsys)


@pytest.fixture
def tools(wired: Fakes) -> OutTools:
    made = OutTools()
    services.register(Tools, made)
    return made


@pytest.fixture
def errands(tools: OutTools) -> Generator[FakeErrands]:
    made = FakeErrands()
    services.register(Errands, made)
    yield made
    services.unregister(Errands)


def known(**changes: object):
    return replace(inbound(speaker_id=ALANA.id), **changes)


def run(wired: Fakes, reply: Reply, said: Inbound | None = None) -> None:
    wired.inference.script = [reply]
    asyncio.run(respond(said or known()))


def test_an_owed_source_that_was_out_of_reach_stores_one_errand_for_the_person_turn(
        wired: Fakes, errands: FakeErrands, logged: Logged) -> None:
    run(wired, OWING)
    assert errands.owed == [(ALANA.household_id, ALANA.id, 1, 100, "house")]
    [done] = logged.events("respond.done")
    assert done["owed"] == "house" and done["owed_dropped"] == "0"


@pytest.mark.parametrize("case", ["unknown speaker", "source answered", "no catalogue", "other source"])
def test_an_owed_the_turn_cannot_support_is_dropped_and_counted(
        wired: Fakes, tools: OutTools, errands: FakeErrands, logged: Logged, case: str) -> None:
    said = inbound(shared=False) if case == "unknown speaker" else known()
    if case == "source answered":
        tools.out = ()
    if case == "no catalogue":
        tools.reachable = False
    if case == "other source":
        tools.out = ("search",)
    run(wired, OWING, said)
    assert errands.owed == []
    [done] = logged.events("respond.done")
    assert done["owed"] == "none" and done["owed_dropped"] == "1"


@pytest.mark.parametrize(("reads", "stored"), [(True, 1), (False, 0)])
def test_an_errand_is_kept_when_the_turn_ran_only_reads_and_dropped_when_it_ran_a_change(
        wired: Fakes, tools: OutTools, errands: FakeErrands, logged: Logged, reads: bool, stored: int) -> None:
    tools.specs = (ToolSpec("lists", "the lists", {"type": "object"}, reads=reads),)
    wired.inference.script = [calls("lists"), OWING]
    asyncio.run(respond(known()))
    assert len(tools.called) == 1 and len(errands.owed) == stored
    [done] = logged.events("respond.done")
    assert done["owed"] == ("house" if stored else "none") and done["owed_dropped"] == str(1 - stored)


def test_a_reply_that_owes_nothing_stores_nothing_and_counts_no_drop(
        wired: Fakes, errands: FakeErrands, logged: Logged) -> None:
    run(wired, PLAIN)
    assert errands.owed == []
    [done] = logged.events("respond.done")
    assert done["owed"] == "none" and done["owed_dropped"] == "0" and done["told"] == ""


def test_a_store_that_cannot_be_reached_does_not_fail_the_turn(wired: Fakes, tools: OutTools, logged: Logged) -> None:
    services.register(Errands, NullErrands())
    try:
        run(wired, PLAIN)
        services.register(Tools, OutTools())
        run(wired, OWING)
    finally:
        services.unregister(Errands)
    assert len(logged.events("respond.done")) == 2
    assert logged.events("respond.errands_unavailable") and logged.events("respond.owed_unrecorded")


def test_finished_errands_are_shown_to_a_known_speaker_and_marked_told_after_her_turn(
        wired: Fakes, errands: FakeErrands, logged: Logged) -> None:
    errands.waiting = (DONE,)
    run(wired, PLAIN)
    assert errands.asked == [(ALANA.id, CONFIG.tell_max, False)]
    assert wired.contexts[0].while_away == ("(Sat 24 Oct 2026 09:00) Added milk to the shopping list.",)
    assert errands.told_ids == [[5]]
    assert logged.events("respond.done")[0]["told"] == "5"


def test_an_unknown_speaker_is_shown_none_and_nothing_is_read(wired: Fakes, errands: FakeErrands) -> None:
    errands.waiting = (DONE,)
    run(wired, PLAIN, inbound(shared=False))
    assert errands.asked == [] and wired.contexts[0].while_away == () and errands.told_ids == []


def test_a_failure_marking_them_told_is_logged_and_the_reply_stands(
        wired: Fakes, errands: FakeErrands, logged: Logged) -> None:
    errands.waiting, errands.down = (DONE,), True
    run(wired, PLAIN)
    assert logged.events("respond.told_unrecorded") and logged.events("respond.done")


def test_an_owner_only_channel_asks_for_the_hearer_alone(wired: Fakes, errands: FakeErrands) -> None:
    run(wired, PLAIN, known(audience="owner"))
    assert errands.asked == [(ALANA.id, CONFIG.tell_max, True)]


def test_a_held_reply_does_not_tell_them_but_the_answer_does(wired: Fakes, errands: FakeErrands, logged: Logged) -> None:
    errands.waiting = (DONE,)
    aside = PLAIN.model_copy(update={"answers": False})
    wired.inference.script = [aside, PLAIN]
    told_at_hold: list[list[list[int]]] = []

    async def scenario() -> None:
        out = await respond(replace(known(), later=True, later_by="turn"))
        assert out.follows
        told_at_hold.append(list(errands.told_ids))
        await until(lambda: logged.events("respond.done"))

    asyncio.run(scenario())
    assert logged.events("respond.held") and told_at_hold == [[]]
    assert errands.told_ids == [[5]]


def test_an_unprompted_turn_reads_no_results(wired: Fakes, errands: FakeErrands) -> None:
    errands.waiting = (DONE,)
    run(wired, PLAIN, known(unprompted=True))
    assert errands.asked == [] and errands.told_ids == []


def test_results_are_not_marked_told_when_her_turn_was_not_stored(wired: Fakes, errands: FakeErrands) -> None:
    errands.waiting = (DONE,)
    wired.conversations.failing_ashley = True
    run(wired, PLAIN)
    assert errands.told_ids == []
