"""`respond.done` now names the offered ids per tier (`standing_facts`, `recalled_facts`) beside the counts, and still
never a fact's text; what it writes is what `seen` reads. Written blind from the contract."""

from collections.abc import Generator, Mapping, Sequence
from datetime import datetime

import pytest
from ashley import logs, services
from ashley.channels.respond import respond
from ashley.conversations.model import Conversation, Kind
from ashley.inference.reply import Reply
from ashley.memory.memory import Memory, MemoryUnavailable
from ashley.memory.model import Asker, Fact, Held, Op, Recalled, Unwritten
from ashley.memory.report import seen

from conversations_support import events
from inference_support import settle
from profile_support import stored_fact
from turns_support import ALANA, HOUSE, World, inbound, world as world

MARK = "zqREPORT4471"


class Tiers(Memory):
    def __init__(self) -> None:
        self.standing: tuple[Recalled, ...] = ()
        self.answer: tuple[Recalled, ...] = ()
        self.down: set[str] = set()

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        if "profile" in self.down:
            raise MemoryUnavailable("down")
        return self.standing

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        if "recall" in self.down:
            raise MemoryUnavailable("down")
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

    async def unwritten(self, idle_after_s: Mapping[Kind, float], limit: int,
                        max_failures: int) -> tuple[Unwritten, ...]:
        raise AssertionError("respond only reads")

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        raise AssertionError("respond only reads")

    async def written_through(self, conversation_id: int) -> int | None:
        raise AssertionError("respond only reads")


def offered(ids: Sequence[int], standing: bool, text: str = "plain") -> tuple[Recalled, ...]:
    return tuple(Recalled(stored_fact(i, text, standing=standing, household_id=HOUSE), True) for i in ids)


@pytest.fixture
def memory(world: World) -> Generator[Tiers]:
    m = Tiers()
    services.register(Memory, m)
    yield m
    services.unregister(Memory)


def written(capsys: pytest.CaptureFixture[str]) -> tuple[str, dict[str, str]]:
    logs.setup()
    capsys.readouterr()
    settle(respond(inbound(speaker_id=ALANA.id)))
    out = capsys.readouterr().out
    (fields,) = events(out, "respond.done")
    return out, fields


def test_the_ids_are_logged_in_the_order_offered(world: World, memory: Tiers,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing, memory.answer = offered([30, 4, 18], True), offered([900, 5], False)
    _, fields = written(capsys)
    assert fields["standing_facts"] == "30,4,18" and fields["recalled_facts"] == "900,5"
    assert fields["standing"] == "3" and fields["recalled"] == "2"


def test_nothing_offered_is_an_empty_list_not_a_missing_field(world: World, memory: Tiers,
                                                              capsys: pytest.CaptureFixture[str]) -> None:
    _, fields = written(capsys)
    assert fields["standing_facts"] == "" and fields["recalled_facts"] == ""


@pytest.mark.parametrize("down", [{"profile"}, {"recall"}, {"profile", "recall"}])
def test_unreachable_memory_is_unavailable_in_both_lists(world: World, memory: Tiers,
                                                          capsys: pytest.CaptureFixture[str], down: set[str]) -> None:
    memory.standing, memory.answer = offered([1], True), offered([2], False)
    memory.down = down
    _, fields = written(capsys)
    assert fields["standing_facts"] == "unavailable" and fields["recalled_facts"] == "unavailable"


def test_unwired_memory_is_unavailable_in_both_lists(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    services.unregister(Memory)
    _, fields = written(capsys)
    assert fields["standing_facts"] == "unavailable" and fields["recalled_facts"] == "unavailable"


def test_the_rest_of_the_line_is_as_it_was(world: World, memory: Tiers, capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing, memory.answer = offered([30], True), offered([5], False)
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(5, 30, 99))
    _, fields = written(capsys)
    for name in ("conversation", "kind", "medium", "tool_rounds", "tool_calls", "speaker", "recalled", "standing",
                 "used_facts", "used_unrecalled", "duration_ms"):
        assert name in fields, name
    assert fields["used_facts"] == "5,30" and fields["used_unrecalled"] == "1" and fields["speaker"] == "known"


def test_no_fact_text_reaches_the_line(world: World, memory: Tiers, capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing = offered([30], True, f"is allergic to {MARK}")
    memory.answer = offered([5], False, f"likes {MARK}")
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(5, 30))
    out, fields = written(capsys)
    assert fields["standing_facts"] == "30" and MARK not in out and "allergic" not in out


def test_the_line_as_written_is_what_seen_reads_back(world: World, memory: Tiers,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    memory.standing, memory.answer = offered([30, 4], True), offered([900, 5], False)
    world.inference.then = Reply(spoken="ok", text="ok", used_facts=(900, 4, 77))
    out, fields = written(capsys)
    (reply,), none = seen(out.splitlines(), int(fields["conversation"]))
    assert none == ()
    assert reply.standing == (30, 4) and reply.recalled == (900, 5) and reply.known_offered
    assert reply.used == (900, 4) and reply.used_unrecalled == 1 and reply.speaker == "known"
    assert reply.kind == fields["kind"] and reply.medium == fields["medium"]


def test_an_unavailable_line_as_written_reads_back_as_none(world: World, memory: Tiers,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    memory.down = {"recall"}
    out, fields = written(capsys)
    (reply,), _ = seen(out.splitlines(), int(fields["conversation"]))
    assert reply.standing is None and reply.recalled is None
