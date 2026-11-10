"""`respond` and long-term memory: `Memory.recall(asker, query)` once per message with the message text and an Asker
(household, the resolved speaker or None, `owner_only` only for the `owner` audience, a timezone-aware now); what comes
back reaches the persona context as `remembered` as given, MemoryUnavailable makes it None and the reply still goes on;
`respond.done` carries `recalled`, `used_facts` and `used_unrecalled` and never fact, query or message text."""

from collections.abc import Generator, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from ashley import logs, services
from ashley.channels.model import Audience
from ashley.channels.respond import respond
from ashley.conversations.model import Conversation, Kind
from ashley.inference.reply import Reply
from ashley.memory.memory import Memory, MemoryUnavailable
from ashley.memory.model import Asker, Fact, Held, Op, Recalled, Unwritten
from conversations_support import events
from inference_support import settle
from turns_support import ALANA, HOUSE, SAM, World, inbound, world as world

MARK = "zqFACT7731"


class FakeMemory(Memory):
    """Answers `recall` with `answer` (or raises `error`) and records each call; the write side is not this path."""

    def __init__(self) -> None:
        self.answer: tuple[Recalled, ...] = ()
        self.error: Exception | None = None
        self.calls: list[tuple[Asker, str]] = []

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        self.calls.append((asker, query))
        if self.error:
            raise self.error
        return self.answer

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        return ()

    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        raise AssertionError("respond only recalls")

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        raise AssertionError("respond only recalls")

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        raise AssertionError("respond only recalls")

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        raise AssertionError("respond only recalls")

    async def embed_missing(self, limit: int) -> int:
        raise AssertionError("respond only recalls")

    async def unwritten(self, idle_after_s: Mapping[Kind, float], limit: int, max_failures: int) -> tuple[Unwritten, ...]:
        raise AssertionError("respond only recalls")

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        raise AssertionError("respond only recalls")

    async def written_through(self, conversation_id: int) -> int | None:
        raise AssertionError("respond only recalls")


def recalled(fact_id: int, text: str = "plain", volunteer: bool = True) -> Recalled:
    when = datetime(2026, 1, 1, tzinfo=UTC)
    return Recalled(Fact(fact_id, HOUSE, None, None, "shared", "other", False, text, 1, when, None, None), volunteer)


@pytest.fixture
def memory(world: World) -> Generator[FakeMemory]:
    m = FakeMemory()
    services.register(Memory, m)
    yield m
    services.unregister(Memory)


def asker_of(memory: FakeMemory) -> Asker:
    (call,) = memory.calls
    return call[0]


def test_recall_is_asked_once_with_the_message_text_as_the_query(world: World, memory: FakeMemory) -> None:
    settle(respond(inbound(text="what tea does Alana like?")))
    assert len(memory.calls) == 1
    assert memory.calls[0][1] == "what tea does Alana like?"


def test_the_asker_carries_the_household(world: World, memory: FakeMemory) -> None:
    settle(respond(inbound()))
    assert asker_of(memory).household_id == HOUSE


def test_a_named_speaker_is_the_askers_speaker(world: World, memory: FakeMemory) -> None:
    settle(respond(inbound(speaker_id=ALANA.id)))
    assert asker_of(memory).speaker_id == ALANA.id


def test_a_named_speaker_wins_over_presence(world: World, memory: FakeMemory) -> None:
    world.presence.answer = frozenset({SAM.id})
    settle(respond(inbound(speaker_id=ALANA.id, shared=True)))
    assert asker_of(memory).speaker_id == ALANA.id


def test_the_one_person_home_is_the_speaker_on_a_shared_channel(world: World, memory: FakeMemory) -> None:
    world.presence.answer = frozenset({SAM.id})
    settle(respond(inbound(shared=True)))
    assert asker_of(memory).speaker_id == SAM.id


@pytest.mark.parametrize("home", [frozenset({ALANA.id, SAM.id}), frozenset[int](), None])
def test_an_unknown_speaker_is_none(world: World, memory: FakeMemory, home: frozenset[int] | None) -> None:
    world.presence.answer = home
    settle(respond(inbound(shared=True)))
    assert asker_of(memory).speaker_id is None


def test_a_personal_channel_never_takes_its_asker_from_presence(world: World, memory: FakeMemory) -> None:
    world.presence.answer = frozenset({SAM.id})
    settle(respond(inbound(shared=False)))
    assert asker_of(memory).speaker_id is None


@pytest.mark.parametrize(("audience", "owner_only"), [("owner", True), ("household", False), ("present", False)])
def test_owner_only_is_true_only_for_the_owner_audience(world: World, memory: FakeMemory, audience: Audience,
                                                        owner_only: bool) -> None:
    settle(respond(inbound(audience=audience, speaker_id=ALANA.id)))
    assert asker_of(memory).owner_only is owner_only


def test_the_asker_is_stamped_with_a_timezone_aware_now(world: World, memory: FakeMemory) -> None:
    before = datetime.now(UTC)
    settle(respond(inbound()))
    at = asker_of(memory).at
    assert at.tzinfo is not None and at.utcoffset() is not None
    assert before - timedelta(seconds=1) <= at <= datetime.now(UTC) + timedelta(seconds=1)


def test_what_recall_returned_reaches_the_persona_as_given_in_order(world: World, memory: FakeMemory) -> None:
    memory.answer = (recalled(30), recalled(4, volunteer=False), recalled(77))
    settle(respond(inbound()))
    assert world.persona.asked[0][1].remembered == memory.answer
    assert [r.fact.id for r in world.persona.asked[0][1].remembered or ()] == [30, 4, 77]


def test_nothing_recalled_is_the_empty_tuple_not_none(world: World, memory: FakeMemory) -> None:
    settle(respond(inbound()))
    assert world.persona.asked[0][1].remembered == ()


def test_memory_unavailable_is_none_and_the_reply_still_goes_on(world: World, memory: FakeMemory) -> None:
    memory.error = MemoryUnavailable("down")
    out = settle(respond(inbound(text="hello")))
    assert world.persona.asked[0][1].remembered is None
    assert out.body
    assert world.conversations.turns_of(out.conversation_id)[-1][0] == "ashley"
    assert len(world.inference.asked) == 1


def test_unwired_memory_reads_as_unavailable(world: World) -> None:
    services.unregister(Memory)
    settle(respond(inbound()))
    assert world.persona.asked[0][1].remembered is None


def test_recall_happens_even_when_the_tools_catalogue_is_unreachable(world: World, memory: FakeMemory) -> None:
    world.tools.on_offer = None
    memory.answer = (recalled(3),)
    settle(respond(inbound()))
    ctx = world.persona.asked[0][1]
    assert ctx.tools_reachable is False
    assert ctx.remembered == memory.answer





def done(world: World, capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    logs.setup()
    capsys.readouterr()
    settle(respond(inbound()))
    (line,) = events(capsys.readouterr().out, "respond.done")
    return line


@pytest.mark.parametrize("count", [0, 1, 3])
def test_done_counts_the_recalled_facts(world: World, memory: FakeMemory, capsys: pytest.CaptureFixture[str],
                                        count: int) -> None:
    memory.answer = tuple(recalled(i + 1) for i in range(count))
    assert done(world, capsys)["recalled"] == str(count)


def test_done_says_unavailable_when_memory_could_not_be_reached(world: World, memory: FakeMemory,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    memory.error = MemoryUnavailable("down")
    line = done(world, capsys)
    assert line["recalled"] == "unavailable"
    assert line["used_facts"] == "" and line["used_unrecalled"] == "0"


def reply_using(*ids: int) -> Reply:
    return Reply(spoken="ok", text="ok", used_facts=ids)


def test_used_facts_are_the_recalled_ids_the_reply_named_in_the_replys_order(world: World, memory: FakeMemory,
                                                                           capsys: pytest.CaptureFixture[str]) -> None:
    memory.answer = (recalled(10), recalled(20), recalled(30))
    world.inference.then = reply_using(30, 10)
    line = done(world, capsys)
    assert line["used_facts"] == "30,10"
    assert line["used_unrecalled"] == "0"


def test_used_facts_drop_repeats_and_keep_first_occurrence(world: World, memory: FakeMemory,
                                                          capsys: pytest.CaptureFixture[str]) -> None:
    memory.answer = (recalled(10), recalled(20))
    world.inference.then = reply_using(20, 10, 20, 10, 20)
    line = done(world, capsys)
    assert line["used_facts"] == "20,10"


def test_ids_not_recalled_are_counted_distinctly_and_left_out_of_used_facts(
        world: World, memory: FakeMemory, capsys: pytest.CaptureFixture[str]) -> None:
    memory.answer = (recalled(10), recalled(20))
    world.inference.then = reply_using(99, 10, 98, 99, 98, 99)
    line = done(world, capsys)
    assert line["used_facts"] == "10"
    assert line["used_unrecalled"] == "2"


def test_a_reply_naming_only_unrecalled_ids_has_empty_used_facts(world: World, memory: FakeMemory,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    memory.answer = (recalled(10),)
    world.inference.then = reply_using(11, 12)
    line = done(world, capsys)
    assert line["used_facts"] == "" and line["used_unrecalled"] == "2"


def test_nothing_recalled_makes_every_named_id_unrecalled(world: World, memory: FakeMemory,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    world.inference.then = reply_using(5, 6, 5)
    line = done(world, capsys)
    assert line["recalled"] == "0" and line["used_facts"] == "" and line["used_unrecalled"] == "2"


def test_a_reply_naming_nothing_uses_nothing(world: World, memory: FakeMemory,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    memory.answer = (recalled(10),)
    line = done(world, capsys)
    assert line["used_facts"] == "" and line["used_unrecalled"] == "0"





def test_no_fact_query_or_message_text_reaches_any_log_line(world: World, memory: FakeMemory,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    memory.answer = (recalled(10, f"likes {MARK} tea"), recalled(20, f"hides {MARK} key", volunteer=False))
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(10, 20, 99))
    logs.setup()
    capsys.readouterr()
    settle(respond(inbound(text=f"what about {MARK}", speaker_id=ALANA.id)))
    memory.error = MemoryUnavailable(f"down {MARK}")
    settle(respond(inbound(text=f"again {MARK}", thread="device:4", speaker_id=ALANA.id)))
    out = capsys.readouterr().out
    assert len(events(out, "respond.done")) == 2, "control: both turns were logged"
    assert memory.calls[0][1] == f"what about {MARK}", "control: the text did reach memory"
    assert MARK not in out
    assert "likes" not in out and "hides" not in out
