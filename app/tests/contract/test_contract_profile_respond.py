"""The turn loop and the standing tier: `profile` and `recall` are fetched for the same asker at the same time, the
profile reaches the persona context as `standing`, either one unreachable makes memory unreachable for the reply,
`used_facts` counts ids from both tiers, and `respond.done` logs `standing`. Written blind from the contract."""

import asyncio
from collections.abc import Generator, Mapping, Sequence
from datetime import datetime

import pytest
from ashley import logs, services
from ashley.channels.respond import respond
from ashley.conversations.model import Conversation, Kind
from ashley.inference.reply import Reply
from ashley.memory.memory import Memory, MemoryUnavailable
from ashley.memory.model import Asker, Fact, Held, Op, Recalled, Unwritten
from conversations_support import events
from inference_support import settle
from profile_support import stored_fact
from turns_support import ALANA, HOUSE, World, inbound, world as world

MARK = "zqSTAND9917"


class TwoTierMemory(Memory):
    """Answers `profile` and `recall` from `standing` and `answer` (or raises the matching error), records each
    call's asker, and lets a test see whether the two calls were in flight together."""

    def __init__(self) -> None:
        self.standing: tuple[Recalled, ...] = ()
        self.answer: tuple[Recalled, ...] = ()
        self.profile_error: Exception | None = None
        self.recall_error: Exception | None = None
        self.profiled: list[Asker] = []
        self.recalled: list[Asker] = []
        self.rendezvous = False
        self.started = {"profile": asyncio.Event(), "recall": asyncio.Event()}
        self.met: dict[str, bool] = {}

    async def _meet(self, me: str, other: str) -> None:
        if not self.rendezvous:
            return
        self.started[me].set()
        try:
            await asyncio.wait_for(self.started[other].wait(), 0.5)
            self.met[me] = True
        except TimeoutError:
            self.met[me] = False

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        self.profiled.append(asker)
        await self._meet("profile", "recall")
        if self.profile_error:
            raise self.profile_error
        return self.standing

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        self.recalled.append(asker)
        await self._meet("recall", "profile")
        if self.recall_error:
            raise self.recall_error
        return self.answer

    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        raise AssertionError("respond only reads")

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        raise AssertionError("respond only reads")

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        raise AssertionError("respond only reads")

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        raise AssertionError("respond only reads")

    async def embed_missing(self, limit: int) -> int:
        raise AssertionError("respond only reads")

    async def unwritten(self, idle_after_s: Mapping[Kind, float], limit: int, max_failures: int) -> tuple[Unwritten, ...]:
        raise AssertionError("respond only reads")

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        raise AssertionError("respond only reads")

    async def written_through(self, conversation_id: int) -> int | None:
        raise AssertionError("respond only reads")


def tier(fact_id: int, standing: bool, text: str = "plain", volunteer: bool = True) -> Recalled:
    return Recalled(stored_fact(fact_id, text, standing=standing, household_id=HOUSE), volunteer)


@pytest.fixture
def memory(world: World) -> Generator[TwoTierMemory]:
    m = TwoTierMemory()
    services.register(Memory, m)
    yield m
    services.unregister(Memory)


def done(capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    logs.setup()
    capsys.readouterr()
    settle(respond(inbound()))
    (line,) = events(capsys.readouterr().out, "respond.done")
    return line


def test_the_profile_is_asked_once_for_the_same_asker_as_recall(world: World, memory: TwoTierMemory) -> None:
    settle(respond(inbound(speaker_id=ALANA.id, audience="owner")))
    (profiled,), (recalled,) = memory.profiled, memory.recalled
    assert (profiled.household_id, profiled.speaker_id, profiled.owner_only) == (HOUSE, ALANA.id, True)
    assert (profiled.household_id, profiled.speaker_id, profiled.owner_only) == (
        recalled.household_id, recalled.speaker_id, recalled.owner_only)


def test_profile_and_recall_are_in_flight_together(world: World, memory: TwoTierMemory) -> None:
    memory.rendezvous = True
    settle(respond(inbound()))
    assert memory.met == {"profile": True, "recall": True}


def test_the_profile_reaches_the_persona_as_standing_in_order_apart_from_what_was_recalled(
        world: World, memory: TwoTierMemory) -> None:
    memory.standing = (tier(30, True), tier(4, True, volunteer=False))
    memory.answer = (tier(77, False),)
    settle(respond(inbound()))
    ctx = world.persona.asked[0][1]
    assert ctx.standing == memory.standing and ctx.remembered == memory.answer


def test_nothing_standing_is_the_empty_tuple(world: World, memory: TwoTierMemory) -> None:
    settle(respond(inbound()))
    assert world.persona.asked[0][1].standing == ()


@pytest.mark.parametrize("failing", ["profile", "recall", "both"])
def test_either_tier_unreachable_makes_memory_unreachable_for_the_reply(world: World, memory: TwoTierMemory,
                                                                        failing: str) -> None:
    memory.standing, memory.answer = (tier(1, True),), (tier(2, False),)
    if failing in ("profile", "both"):
        memory.profile_error = MemoryUnavailable("down")
    if failing in ("recall", "both"):
        memory.recall_error = MemoryUnavailable("down")
    out = settle(respond(inbound()))
    ctx = world.persona.asked[0][1]
    assert ctx.remembered is None and ctx.standing == ()
    assert out.body and len(world.inference.asked) == 1


def test_unwired_memory_is_unreachable_for_both_tiers(world: World) -> None:
    services.unregister(Memory)
    settle(respond(inbound()))
    ctx = world.persona.asked[0][1]
    assert ctx.remembered is None and ctx.standing == ()


@pytest.mark.parametrize("count", [0, 1, 3])
def test_done_counts_the_standing_facts(world: World, memory: TwoTierMemory, capsys: pytest.CaptureFixture[str],
                                        count: int) -> None:
    memory.standing = tuple(tier(i + 1, True) for i in range(count))
    memory.answer = (tier(50, False),)
    line = done(capsys)
    assert line["standing"] == str(count) and line["recalled"] == "1"


@pytest.mark.parametrize("failing", ["profile", "recall"])
def test_done_says_unavailable_for_standing_when_memory_could_not_be_reached(
        world: World, memory: TwoTierMemory, capsys: pytest.CaptureFixture[str], failing: str) -> None:
    setattr(memory, f"{failing}_error", MemoryUnavailable("down"))
    line = done(capsys)
    assert line["standing"] == "unavailable" and line["recalled"] == "unavailable"


def test_used_facts_count_ids_from_both_tiers_in_the_replys_order(world: World, memory: TwoTierMemory,
                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing = (tier(100, True), tier(101, True))
    memory.answer = (tier(10, False), tier(20, False))
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(20, 101, 100, 99, 20, 99))
    line = done(capsys)
    assert line["used_facts"] == "20,101,100"
    assert line["used_unrecalled"] == "1"


def test_a_standing_id_counts_as_offered_when_nothing_was_recalled(world: World, memory: TwoTierMemory,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing = (tier(100, True),)
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(100, 5))
    line = done(capsys)
    assert line["used_facts"] == "100" and line["used_unrecalled"] == "1"


def test_an_id_in_neither_tier_is_still_unrecalled(world: World, memory: TwoTierMemory,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing, memory.answer = (tier(100, True),), (tier(10, False),)
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(7, 8, 7))
    line = done(capsys)
    assert line["used_facts"] == "" and line["used_unrecalled"] == "2"


def test_no_standing_fact_text_reaches_any_log_line(world: World, memory: TwoTierMemory,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing = (tier(100, True, f"is allergic to {MARK}"),)
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(100,))
    logs.setup()
    capsys.readouterr()
    settle(respond(inbound(speaker_id=ALANA.id)))
    memory.profile_error = MemoryUnavailable(f"down {MARK}")
    settle(respond(inbound(thread="device:4", speaker_id=ALANA.id)))
    out = capsys.readouterr().out
    assert len(events(out, "respond.done")) == 2, "control: both turns were logged"
    assert MARK not in out and "allergic" not in out
