"""`Reply.memory`: in a remembered conversation her act is carried out after the reply is returned: `keep` and `correct`
through `memory.remember` over the person's turn and hers, `forget` by deleting the facts she names that the speaker
may forget. How it ended is logged as `respond.memory_acted`; her turn stores nothing of it. The ids she names that she
was not shown are dropped. A failure is logged with ids and a kind, never text, and the reply stands. Nothing runs when
she did not ask or the conversation is not remembered."""

import asyncio
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels import keep
from ashley.conversations.model import Conversation
from ashley.inference.reply import MemoryAct, Reply
from ashley.live.events import ThreadTurn
from ashley.live.live import Live
from ashley.memory.memory import Memory, NullMemory
from ashley.memory.model import Asker, Fact, Held, Recalled, Source
from ashley.memory.remember import Remembered, RememberUnavailable
from later_support import Logged, until
from live_support import FakeLive
from respond_support import ALANA, Fakes, inbound, wired as wired
from ashley.channels.respond import respond

ASKED = Reply(spoken="Noted.", text="Noted.", memory=MemoryAct(action="keep", facts=()))
PLAIN = ASKED.model_copy(update={"memory": None})


def acting(action: str, *facts: int) -> Reply:
    return ASKED.model_copy(update={"memory": MemoryAct.model_validate({"action": action, "facts": facts})})


def fact(fact_id: int) -> Fact:
    return Fact(fact_id, ALANA.household_id, None, None, "shared", "other", False, "text", 1,
                datetime(2026, 1, 1, tzinfo=UTC), None, None)


@dataclass
class Shown(NullMemory):
    """Memory that shows her `shown` and lets the speaker forget `mine`; records what was forgotten."""

    shown: tuple[int, ...] = ()
    mine: tuple[int, ...] = ()
    forgotten: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        return tuple(Recalled(fact(i), True) for i in self.shown)

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        return ()

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        return tuple(Held(fact(i), None, Source(1, "chat", datetime(2026, 1, 1, tzinfo=UTC), True)) for i in self.mine if i == fact_id)

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        self.forgotten.append((fact_id, by))
        return 1


@pytest.fixture
def memory() -> Generator[Shown]:
    made = Shown()
    services.register(Memory, made)
    yield made
    services.unregister(Memory)


@pytest.fixture
def logged(capsys: pytest.CaptureFixture[str]) -> Logged:
    return Logged(capsys)


@pytest.fixture
def live() -> Generator[FakeLive]:
    made = FakeLive()
    services.register(Live, made)
    yield made
    services.unregister(Live)


class Remembering:
    def __init__(self, fail: Exception | None = None, inserted: tuple[int, ...] = (1,), ended: int = 0,
                 replaced: int = 0) -> None:
        self.calls: list[tuple[Conversation, int, int | None, tuple[int, ...]]] = []
        self.fail = fail
        self.inserted = inserted
        self.ended = ended
        self.replaced = replaced

    async def __call__(self, conversation: Conversation, turn_id: int, answer: int | None,
                       targets: tuple[int, ...]) -> Remembered:
        self.calls.append((conversation, turn_id, answer, targets))
        if self.fail is not None:
            raise self.fail
        return Remembered(self.inserted, self.ended, self.replaced)


@pytest.fixture
def remembering(monkeypatch: pytest.MonkeyPatch) -> Remembering:
    made = Remembering()
    monkeypatch.setattr(keep, "remember", made)
    return made


def web(**changes: object):
    return replace(inbound(thread=f"person:{ALANA.id}:web", kind="chat", shared=False, speaker_id=ALANA.id),
                   audience="owner", place=None, **changes)


def hers(wired: Fakes):
    return next(iter(wired.conversations.convs.values())).turns[-1]


def test_asking_remembers_the_persons_turn_apart_from_the_reply_and_tells_the_screens_nothing_more(
        wired: Fakes, live: FakeLive, remembering: Remembering, logged: Logged) -> None:
    wired.inference.script = [ASKED]

    async def scenario() -> None:
        await respond(web())
        await until(lambda: remembering.calls)
        await until(lambda: logged.events("respond.memory_acted"))

    asyncio.run(scenario())
    assert len([e for e in live.published if isinstance(e, ThreadTurn)]) == 2
    conversation, turn, answer, targets = remembering.calls[0]
    assert next(t for t in conversation.turns if t.id == turn).author == "person"
    assert turn == 100 and answer == hers(wired).id and targets == ()


@pytest.mark.parametrize(("inserted", "ended", "replaced", "fail", "state"), [
    ((7,), 0, 0, None, "kept"),
    ((), 0, 0, None, "known"),
    ((), 1, 0, None, "changed"),
    ((8,), 0, 1, None, "changed"),
    ((), 0, 0, RememberUnavailable("down"), "failed"),
])
def test_how_keeping_it_ended_is_logged_and_not_stored(wired: Fakes, live: FakeLive, remembering: Remembering,
                                                       logged: Logged, inserted: tuple[int, ...], ended: int,
                                                       replaced: int, fail: Exception | None, state: str) -> None:
    remembering.inserted, remembering.ended, remembering.replaced = inserted, ended, replaced
    remembering.fail = fail
    wired.inference.script = [ASKED]

    async def scenario() -> None:
        await respond(web())
        await until(lambda: logged.events("respond.memory_acted"))

    asyncio.run(scenario())
    [acted] = logged.events("respond.memory_acted")
    assert acted["outcome"] == state and acted["action"] == "keep" and acted["turn"] == "100"
    assert not [call for call in wired.conversations.calls if call[0] == "set_kept"]


def test_a_reply_that_does_not_ask_keeps_nothing(wired: Fakes, live: FakeLive, remembering: Remembering) -> None:
    wired.inference.script = [PLAIN]
    asyncio.run(respond(web()))
    assert remembering.calls == []


def test_a_conversation_that_is_not_remembered_keeps_nothing(
        wired: Fakes, live: FakeLive, remembering: Remembering) -> None:
    wired.inference.script = [ASKED]
    asyncio.run(respond(web(remembers=False)))
    assert remembering.calls == []


def test_a_failed_save_is_logged_without_text_and_the_reply_stands(
        wired: Fakes, live: FakeLive, remembering: Remembering, logged: Logged) -> None:
    remembering.fail = RememberUnavailable("down")
    wired.inference.script = [ASKED]

    async def scenario() -> str:
        out = await respond(web(text="remember the cat litter"))
        await until(lambda: logged.events("respond.keep_failed"))
        return out.body

    assert asyncio.run(scenario()) == "Noted."
    failed = logged.events("respond.keep_failed")[0]
    assert failed["reason"] == "RememberUnavailable" and failed["turn"] == "100"
    assert "Jimmy" not in logged.read()


def run(wired: Fakes, logged: Logged, reply: Reply, state: str | None = None, **changes: object) -> None:
    wired.inference.script = [reply]

    async def scenario() -> None:
        await respond(web(**changes))
        await until(lambda: logged.events("respond.memory_acted"))

    asyncio.run(scenario())
    assert state is None or logged.events("respond.memory_acted")[0]["outcome"] == state


def test_a_correction_hands_the_writer_the_facts_she_named_that_she_was_shown(
        wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged) -> None:
    memory.shown = (4, 5)
    run(wired, logged, acting("correct", 4), "kept")
    assert remembering.calls[0][3] == (4,)


def test_an_id_she_was_not_shown_is_dropped_and_logged_by_id_only(
        wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged) -> None:
    memory.shown = (4,)
    run(wired, logged, acting("correct", 4, 99), text="the cat litter note is wrong")
    assert remembering.calls[0][3] == (4,)
    [dropped] = logged.events("respond.memory_act_unknown_fact")
    assert dropped["unknown"] == "99" and dropped["action"] == "correct" and "Jimmy" not in logged.read()


@pytest.mark.parametrize("action", ["correct", "forget"])
def test_a_correction_or_forget_naming_nothing_she_was_shown_changes_nothing_and_says_so(
        wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged, action: str) -> None:
    memory.shown, memory.mine = (4,), (4, 99)
    run(wired, logged, acting(action, 99), "missing")
    assert remembering.calls == [] and memory.forgotten == []


def test_a_forget_is_done_by_deleting_the_facts_the_speaker_may_forget_and_never_by_the_writer(
        wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged) -> None:
    memory.shown, memory.mine = (4, 5), (4,)
    run(wired, logged, acting("forget", 4, 5), "changed")
    assert memory.forgotten == [(4, ALANA.id)] and remembering.calls == []


def test_a_forget_of_a_fact_the_speaker_may_not_forget_is_refused_and_logged(
        wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged) -> None:
    memory.shown, memory.mine = (5,), ()
    run(wired, logged, acting("forget", 5), "missing")
    assert memory.forgotten == [] and [e["fact"] for e in logged.events("respond.memory_act_refused")] == ["5"]


def test_only_a_known_speaker_forgets(wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged) -> None:
    memory.shown, memory.mine = (4,), (4,)
    run(wired, logged, acting("forget", 4), "missing", speaker_id=None)
    assert memory.forgotten == []


def test_a_keep_ignores_the_ids_it_carries(wired: Fakes, live: FakeLive, remembering: Remembering, memory: Shown, logged: Logged) -> None:
    memory.shown = (4,)
    run(wired, logged, acting("keep", 4), "kept")
    assert remembering.calls[0][3] == ()
