"""In-memory fakes of every system `channels.respond` reaches, registered in the locator by the `wired` fixture, and a
fake `persona.system` that records the context it was given."""

import itertools
from collections.abc import Generator, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TypeVar

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.conversations.conversations import ConversationClosed, Conversations, ConversationsUnavailable
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Carried, Channel, Conversation, Cursor, Hearer, Kind, NewTurn, Page, Turn
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.runs.runs import Runs
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.services import Service
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
ALANA, SAM = Person(1, 10, "Alana"), Person(2, 10, "Sam")
HOME = Household(10, "home", "America/Denver", "", (ALANA, SAM))
EPOCH = datetime(2026, 10, 25, tzinfo=UTC)


class FakePeople(People):
    async def household(self, household_id: int) -> Household | None:
        return HOME if household_id == HOME.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class FakePresence(Presence):
    answer: frozenset[int] | None = None

    async def home(self, household_id: int) -> frozenset[int] | None:
        return self.answer


@dataclass
class FakeConversations(Conversations):
    """One conversation per thread. `closing` turns the next n person turns away as closed, starting another one;
    `failing_ashley` refuses her turns."""

    convs: dict[int, Conversation] = field(default_factory=dict[int, Conversation])
    threads: dict[str, int] = field(default_factory=dict[str, int])
    opened: dict[int, tuple[Channel | None, str | None]] = field(default_factory=dict[int, tuple[Channel | None, str | None]])
    closing: int = 0
    failing_ashley: bool = False
    calls: list[tuple[str, object]] = field(default_factory=list[tuple[str, object]])
    carry_calls: list[tuple[Hearer, int, int, str, int, int]] = field(
        default_factory=list[tuple[Hearer, int, int, str, int, int]])
    relevant: tuple[Turn, ...] = ()
    filtered: int = 0
    added: list[NewTurn] = field(default_factory=list[NewTurn])
    _ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    async def start(self, household_id: int, kind: Kind, participants: Iterable[int],
                    remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        cid = next(self._ids)
        made = Conversation(cid, household_id, kind, frozenset(participants), EPOCH, EPOCH, "open", ())
        self.convs[cid] = made
        self.opened[cid] = (channel, place)
        return made

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        self.calls.append(("add_turn", (conversation_id, turn)))
        self.added.append(turn)
        if turn.author == "person" and self.closing:
            self.closing -= 1
            self.threads.clear()
            raise ConversationClosed(conversation_id)
        if turn.author == "ashley" and self.failing_ashley:
            raise ConversationsUnavailable("down")
        if turn.carried_from is not None:
            for held in self.convs.values():
                for t in held.turns:
                    if t.carried_from == turn.carried_from:
                        return t
        conv = self.convs[conversation_id]
        stored = Turn(len(conv.turns) + 100, turn.author, turn.speaker_id, turn.text, EPOCH, turn.follows,
                      conversation_id, answers=turn.answers, carried_from=turn.carried_from,
                      continued_on=turn.continued_on, attachment=turn.attachment, spoken=turn.spoken,
                      receipts=turn.receipts)
        self.convs[conversation_id] = replace(conv, turns=(*conv.turns, stored))
        return stored

    async def for_thread(self, household_id: int, thread: str, kind: Kind, participants: Iterable[int],
                         remembered: bool = True, channel: Channel | None = None,
                         place: str | None = None) -> Conversation:
        people = tuple(participants)
        self.calls.append(("for_thread", (household_id, thread, kind, people)))
        if thread not in self.threads:
            self.threads[thread] = (await self.start(household_id, kind, people, channel=channel, place=place)).id
        return self.convs[self.threads[thread]]

    async def get(self, conversation_id: int) -> Conversation | None:
        return self.convs.get(conversation_id)

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        raise AssertionError("not used")

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        cid = self.threads.get(thread)
        found = None if cid is None else self.convs[cid]
        return found if found is not None and found.household_id == household_id else None

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        raise AssertionError("not used")

    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        raise AssertionError("not used")

    async def carried(self, hearer: Hearer, conversation_id: int, before: int, query: str, recent: int,
                      relevant: int) -> Carried:
        """The conversation's own turns before `before`, the last `recent` of them, and `relevant` and `filtered` as
        set: no other conversation and no filter, which the Postgres contract tests cover."""
        self.carry_calls.append((hearer, conversation_id, before, query, recent, relevant))
        earlier = [t for t in self.convs[conversation_id].turns if t.id < before]
        return Carried(tuple(earlier[len(earlier) - recent:] if recent else ()), self.relevant, self.filtered)


@dataclass
class FakeTools(Tools):
    specs: tuple[ToolSpec, ...] = (ToolSpec("lights", "the lights", {"type": "object"}, reads=True),)
    reachable: bool = True
    result: str = "ok"
    called: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        if not self.reachable:
            raise ToolsUnavailable("down")
        return Catalogue(self.specs, "use the tools")

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call)
        return ToolResult(call.id, self.result)


@dataclass
class FakeInference(Inference):
    """Answers each step from `script`, in order: a ToolCalls, a reply (a Reply, or another model re-read as the step's
    `output`), or an exception to raise. `tasks` and `prompts` are what each step was asked."""

    script: list[ToolCalls | BaseModel | Exception] = field(default_factory=list[ToolCalls | BaseModel | Exception])
    prompts: list[Prompt] = field(default_factory=list[Prompt])
    tasks: list[Task] = field(default_factory=list[Task])

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("respond steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("respond does not listen")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("respond does not speak")

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.prompts.append(prompt)
        self.tasks.append(task)
        got = self.script.pop(0)
        if isinstance(got, Exception):
            raise got
        if isinstance(got, ToolCalls):
            return got
        return output.model_validate(got.model_dump())


@dataclass
class Fakes:
    people: FakePeople
    presence: FakePresence
    conversations: FakeConversations
    tools: FakeTools
    inference: FakeInference
    contexts: list[persona.Context]


def asked_last(prompt: Prompt) -> Message:
    """The last message of a step's prompt, which is a message and not a tool round."""
    last = prompt.messages[-1]
    assert isinstance(last, Message)
    return last


def calls(*names: str, prefix: str = "c") -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"{prefix}{i}", name, {"call": f"{prefix}{i}"}) for i, name in enumerate(names)))


def inbound(text: str = "hello", thread: str = "device:7", medium: str = "text", shared: bool = True,
            speaker_id: int | None = None, kind: Kind = "command") -> Inbound:
    return Inbound(HOME.id, thread, text, kind, "spoken" if medium == "spoken" else "text", "present", speaker_id,
                   shared, "kitchen", "device")


_INTERFACES: tuple[type[Service], ...] = (People, Presence, Conversations, InFlight, Tools, Inference, Runs)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Generator[Fakes]:
    fakes = Fakes(FakePeople(), FakePresence(), FakeConversations(), FakeTools(), FakeInference(), [])

    def system(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        fakes.contexts.append(context)
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", system)
    services.register(People, fakes.people)
    services.register(Presence, fakes.presence)
    services.register(Conversations, fakes.conversations)
    services.register(InFlight, InFlight.null())
    services.register(Tools, fakes.tools)
    services.register(Inference, fakes.inference)
    yield fakes
    for interface in _INTERFACES:
        services.unregister(interface)
