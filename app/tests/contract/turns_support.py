"""Helpers for the blind `respond` tests: in-memory fakes of every system the turn loop reaches through the locator
(People, Presence, Conversations, Tools, Inference) and of `persona.system`, each recording what it was asked, wired by
the `world` fixture and unwired after. The fakes assert nothing themselves; the tests read what they recorded."""

import json
from collections.abc import Generator, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any, TypeVar

import pytest
from ashley import services
from ashley.channels import respond as respond_module
from ashley.channels.model import Audience, Inbound, Medium
from ashley.conversations.conversations import ConversationClosed, Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Carried, Channel, Conversation, Cursor, Hearer, Kind, NewTurn, Page, Turn
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.persona import persona as persona_module
from ashley.persona.persona import Context
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
HOUSE = 5
ALANA = Person(11, HOUSE, "Alana")
SAM = Person(12, HOUSE, "Sam")
HOUSEHOLD = Household(HOUSE, "home", "America/Denver", "a dog named Pip", (ALANA, SAM))
LIMITS: dict[str, dict[str, int]] = json.loads((Path(respond_module.__file__).parent / "turns.json").read_text())
SPEC = ToolSpec("lights", "Which lights are on", {"type": "object", "properties": {}}, reads=True)
OTHER_SPEC = ToolSpec("weather", "The forecast", {"type": "object", "properties": {}}, reads=True)


def inbound(text: str = "turn on the lights", thread: str = "device:3", kind: Kind = "command",
            medium: Medium = "spoken", audience: Audience = "present", speaker_id: int | None = None,
            shared: bool = True, place: str | None = "kitchen") -> Inbound:
    return Inbound(HOUSE, thread, text, kind, medium, audience, speaker_id, shared, place, "device")


class FakePeople(People):
    def __init__(self) -> None:
        self.households = {HOUSE: HOUSEHOLD}
        self.calls = 0
        self.error: Exception | None = None

    async def household(self, household_id: int) -> Household | None:
        self.calls += 1
        if self.error:
            raise self.error
        return self.households.get(household_id)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        self.calls += 1
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Any, ...]:
        self.calls += 1
        return ()


class FakePresence(Presence):
    def __init__(self) -> None:
        self.answer: frozenset[int] | None = None
        self.calls = 0

    async def home(self, household_id: int) -> frozenset[int] | None:
        self.calls += 1
        return self.answer


@dataclass
class ThreadCall:
    household_id: int
    thread: str
    kind: Kind
    participants: tuple[int, ...]


@dataclass
class FakeConversations(Conversations):
    """Conversations in memory. `closing` names how many person turns are refused ConversationClosed (each refusal
    closes the thread's conversation, so the next `for_thread` starts another); `error` fails every call; `ashley_error`
    fails storing her turns only."""

    ids: Iterator[int] = field(default_factory=lambda: count(41))
    threads: dict[str, int] = field(default_factory=dict[str, int])
    stored: dict[int, Conversation] = field(default_factory=dict[int, Conversation])
    thread_calls: list[ThreadCall] = field(default_factory=list[ThreadCall])
    added: list[tuple[int, NewTurn]] = field(default_factory=list[tuple[int, NewTurn]])
    closing: int = 0
    error: Exception | None = None
    ashley_error: Exception | None = None
    turn_ids: Iterator[int] = field(default_factory=lambda: count(900))
    carry_calls: list[tuple[Hearer, int, int, str, int, int]] = field(
        default_factory=list[tuple[Hearer, int, int, str, int, int]])

    def seed(self, thread: str, kind: Kind, turns: Iterable[NewTurn]) -> int:
        cid = self._new(HOUSE, kind, ())
        self.threads[thread] = cid
        for turn in turns:
            self._store(cid, turn)
        return cid

    def _new(self, household_id: int, kind: Kind, participants: Iterable[int]) -> int:
        cid = next(self.ids)
        now = datetime.now(UTC)
        self.stored[cid] = Conversation(cid, household_id, kind, frozenset(participants), now, now, "open", ())
        return cid

    def _store(self, cid: int, turn: NewTurn) -> Turn:
        c = self.stored[cid]
        stored = Turn(next(self.turn_ids), turn.author, turn.speaker_id, turn.text, datetime.now(UTC), turn.follows,
                       answers=turn.answers, spoken=turn.spoken)
        speakers = {turn.speaker_id} if turn.speaker_id is not None else set[int]()
        self.stored[cid] = replace(c, turns=(*c.turns, stored), participants=c.participants | speakers,
                                   last_activity_at=stored.at)
        return stored

    async def start(self, household_id: int, kind: Kind, participants: Iterable[int],
                    remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        raise AssertionError("respond starts conversations through for_thread")

    async def for_thread(self, household_id: int, thread: str, kind: Kind, participants: Iterable[int],
                         remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        self.thread_calls.append(ThreadCall(household_id, thread, kind, tuple(participants)))
        if self.error:
            raise self.error
        if thread not in self.threads:
            self.threads[thread] = self._new(household_id, kind, self.thread_calls[-1].participants)
        return self.stored[self.threads[thread]]

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        self.added.append((conversation_id, turn))
        if self.error:
            raise self.error
        if turn.author == "person" and self.closing:
            self.closing -= 1
            self.threads = {t: c for t, c in self.threads.items() if c != conversation_id}
            raise ConversationClosed(f"conversation {conversation_id} is closed")
        if turn.author == "ashley" and self.ashley_error:
            raise self.ashley_error
        return self._store(conversation_id, turn)

    async def get(self, conversation_id: int) -> Conversation | None:
        if self.error:
            raise self.error
        return self.stored.get(conversation_id)

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        raise AssertionError("not used")

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        cid = self.threads.get(thread)
        found = None if cid is None else self.stored[cid]
        return found if found is not None and found.household_id == household_id else None

    def turns_of(self, conversation_id: int) -> list[tuple[str, int | None, str]]:
        return [(t.author, t.speaker_id, t.text) for t in self.stored[conversation_id].turns]

    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        raise AssertionError("not used")

    async def carried(self, hearer: Hearer, conversation_id: int, before: int, query: str, recent: int,
                      relevant: int) -> Carried:
        """The conversation's own turns before `before`, the last `recent` of them: no other conversation and no
        filter, which the Postgres contract tests cover."""
        self.carry_calls.append((hearer, conversation_id, before, query, recent, relevant))
        if self.error:
            raise self.error
        earlier = [t for t in self.stored[conversation_id].turns if t.id < before]
        return Carried(tuple(earlier[len(earlier) - recent:] if recent else ()), (), 0)


class FakeTools(Tools):
    def __init__(self) -> None:
        self.on_offer: Catalogue | None = Catalogue((SPEC, OTHER_SPEC), "use the lights tool for lights")
        self.results: dict[str, ToolResult] = {}
        self.called: list[ToolCall] = []

    async def catalogue(self) -> Catalogue:
        if self.on_offer is None:
            raise ToolsUnavailable("unreachable")
        return self.on_offer

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        found = self.results.get(call.name)
        content = found.content if found else f'{{"ok": true, "call": "{call.id}"}}'
        return ToolResult(call.id, content, found.is_error if found else False)


@dataclass
class Asked:
    task: Task
    prompt: Prompt
    output: type[BaseModel]


class FakeInference(Inference):
    """Answers each `step` with the next scripted outcome: a `Reply`, a `ToolCalls`, or an exception to raise. Once
    the script runs out it keeps answering `then`, so a model that always asks for tools is one line."""

    def __init__(self) -> None:
        self.script: list[Reply | ToolCalls | Exception] = []
        self.then: Reply | ToolCalls | Exception = Reply(spoken="The lights are on.", text="**Lights on.**")
        self.asked: list[Asked] = []

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("respond uses step")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("respond does not listen")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("respond does not speak")

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.asked.append(Asked(task, prompt, output))
        outcome = self.script.pop(0) if self.script else self.then
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ToolCalls) and prompt.tool_choice != "none":
            return outcome
        reply = outcome if isinstance(outcome, Reply) else Reply(spoken="done", text="done")
        return output.model_validate(reply.model_dump())


def asks(*names: str, round_: int = 0) -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"r{round_}c{i}", name, {"n": i, "round": round_}) for i, name in enumerate(names)))


class FakePersona:
    def __init__(self) -> None:
        self.asked: list[tuple[Kind, Context]] = []
        self.prompts: Mapping[str, SystemPrompt] = {"default": SystemPrompt("you are her"),
                                                    "openai": SystemPrompt("you are her, tuned")}

    def __call__(self, kind: Kind, context: Context) -> Mapping[str, SystemPrompt]:
        self.asked.append((kind, context))
        return self.prompts


@dataclass
class World:
    people: FakePeople
    presence: FakePresence
    conversations: FakeConversations
    tools: FakeTools
    inference: FakeInference
    persona: FakePersona

    def touched(self) -> int:
        """How many calls anything has seen."""
        return (self.people.calls + self.presence.calls + len(self.conversations.thread_calls)
                + len(self.conversations.added) + len(self.tools.called) + len(self.inference.asked)
                + len(self.persona.asked))


SERVICES: tuple[type[Any], ...] = (People, Presence, Conversations, InFlight, Tools, Inference)


def register(w: World) -> None:
    """Wire the fakes, again after anything (the app factory) wired real ones over them."""
    services.register(People, w.people)
    services.register(Presence, w.presence)
    services.register(Conversations, w.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Tools, w.tools)
    services.register(Inference, w.inference)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    w = World(FakePeople(), FakePresence(), FakeConversations(), FakeTools(), FakeInference(), FakePersona())
    register(w)
    monkeypatch.setattr(persona_module, "system", w.persona)
    monkeypatch.setattr(respond_module, "system", w.persona, raising=False)   # in case it imported the name
    yield w
    for interface in SERVICES:
        services.unregister(interface)
