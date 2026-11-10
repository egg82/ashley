"""Support for the blind escalation tests: a scripted model that records the task and tool choice of each step, a lamp
tool, an injectable clock and a recorder of `Steps.escalate`, for driving `channels.tool_loop` directly; and web chat
turns through `respond` over real Conversations and PostgresInFlight for the end-to-end cases. A pod's death is a cancel
of the turn's tasks; its claim then runs out by the database's clock."""

import asyncio
import math
from collections.abc import AsyncGenerator, Coroutine, Generator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from ashley import services
from ashley.channels import tool_loop
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.escalation import Escalation, Trigger
from ashley.channels.limits import Limits
from ashley.channels.model import Inbound
from ashley.channels.steps import Steps
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import (Entry, Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolChoice, ToolResult,
                                    ToolSpec)
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.signin.model import SignedIn
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, run, scalar

CLAIM_S = 0.3
SENTINEL = "zq7-sentinel-4417"
SWITCH = ToolSpec("switch_on", "turn something on", {"type": "object"}, reads=False, outside=False)
SYSTEM = {"default": SystemPrompt("system")}
DONE = Reply(spoken="The lamp is on.", text="The lamp is on.")
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
THINKING = "Let me think that through."


class Hang(Exception):
    """A step scripted as `HANG` waits until its runner is killed."""


HANG = Hang()
Step = ToolCalls | Reply | Hang


def switch_on(n: int = 1, aside: str | None = None) -> ToolCalls:
    """The `n`th round of switch-on calls; each one is distinct, so none repeats another."""
    args: dict[str, Any] = {"what": f"lamp{n}", "aside": aside if aside is not None else f"Aside {n}."}
    return ToolCalls((ToolCall(f"c{n}", SWITCH.name, args),))


def rounds(count: int, start: int = 1) -> list[Step]:
    return [switch_on(n) for n in range(start, start + count)]


def escalating(line: str = THINKING) -> Reply:
    """A reply by which the fast model asks for the stronger route."""
    return Reply(spoken="unused", text="unused", escalate=line)


@dataclass(frozen=True)
class Seen:
    task: Task
    tool_choice: ToolChoice
    tools: tuple[str, ...]
    messages: tuple[Entry, ...]


@dataclass
class Model(Inference):
    script: list[Step] = field(default_factory=list[Step])
    seen: list[Seen] = field(default_factory=list[Seen])
    asked: asyncio.Event = field(default_factory=asyncio.Event)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.seen.append(Seen(task, prompt.tool_choice, tuple(t.name for t in prompt.tools), prompt.messages))
        got = self.script.pop(0)
        if got is HANG:
            self.asked.set()
            await asyncio.Event().wait()
        assert not isinstance(got, Hang)
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")

    @property
    def tasks(self) -> list[Task]:
        return [s.task for s in self.seen]

    def choices(self, task: Task) -> list[ToolChoice]:
        return [s.tool_choice for s in self.seen if s.task == task]


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass
class Lamp(Tools):
    """Runs every call; each takes `seconds` of the `clock`, or the next of `takes` first."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])
    clock: Clock | None = None
    seconds: float = 0.0
    takes: list[float] = field(default_factory=list[float])
    hang: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)

    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        self.reached.set()
        if self.clock is not None:
            self.clock.now += self.takes.pop(0) if self.takes else self.seconds
        if self.hang:
            await asyncio.Event().wait()
        return ToolResult(call.id, '{"on": true}')


class Marks(Steps):
    """What a turn recorded of its escalation; `escalate` is the only thing it keeps."""

    def __init__(self, already: Trigger | None = None) -> None:
        self.marked: list[Trigger] = []
        self._set: Trigger | None = already

    @property
    def escalated(self) -> Trigger | None:
        return self._set

    async def escalate(self, trigger: Trigger) -> None:
        self.marked.append(trigger)
        self._set = trigger


def limits(max_rounds: int = 2, *, hold_after: float = math.inf, deadline: float = math.inf,
           escalates: bool = False) -> Limits:
    return Limits(max_tool_rounds=max_rounds, max_tool_result_chars=1000, recent_turns=5, relevant_turns=0,
                  hold_after_s=hold_after, deadline_s=deadline, escalates=escalates)


def stronger(max_rounds: int = 4, *, deadline: float = math.inf) -> Escalation:
    """An escalation whose limits count rounds on from where the fast route stopped."""
    return Escalation(limits(max_rounds, deadline=deadline))


def done[R](scenario: Coroutine[Any, Any, R]) -> R:
    """Run `scenario` to the end and return what it returned."""
    out: list[R] = []

    async def go() -> None:
        out.append(await scenario)

    run(go())
    return out[0]


async def drive(lim: Limits, escalation: Escalation | None, *, hold: bool = False, lamp: Lamp | None = None,
                marks: Marks | None = None, clock: Clock | None = None, started: float | None = None,
                tools: tuple[ToolSpec, ...] = (SWITCH,)) -> tuple[tool_loop.Answer | tool_loop.Held, Marks]:
    """One chat turn through `tool_loop.answer` on the located model, and what it recorded."""
    recorded = marks if marks is not None else Marks()
    when = clock if clock is not None else Clock()
    got = await tool_loop.answer("chat", SYSTEM, (Message("person", "turn on the lamps"),), tools, lim, 1, hold,
                                 lamp if lamp is not None else Lamp(), when.now if started is None else started, when, recorded, None, "text",
                                 escalation)
    return got, recorded


async def carried_on(held: tool_loop.Held, lim: Limits, escalation: Escalation | None, *, lamp: Lamp | None = None,
                     marks: Marks | None = None, clock: Clock | None = None,
                     tools: tuple[ToolSpec, ...] = (SWITCH,)) -> tool_loop.Answer:
    """`tool_loop.resume` of a held turn, as the background half of a held chat turn runs it."""
    when = clock if clock is not None else Clock()
    return await tool_loop.resume(held, "chat", SYSTEM, tools, lim, 1, lamp if lamp is not None else Lamp(), when.now,
                                  when, marks if marks is not None else Marks(), None, "text", escalation)


@dataclass
class OnePerson(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


class Nobody(Presence):
    async def home(self, household_id: int) -> frozenset[int] | None:
        return None


@dataclass
class Pod:
    model: Model
    tools: Lamp


@dataclass
class World:
    url: str
    who: Person
    first: Pod
    second: Pod

    def inbound(self, text: str = "turn on the lamps", kind: Kind = "chat") -> Inbound:
        base = inbound_from(SignedIn(1, self.who), ChatRequest(text=text))
        return replace(base, kind=kind)

    def as_pod(self, pod: Pod) -> None:
        services.register(Inference, pod.model)
        services.register(Tools, pod.tools)

    def turns(self) -> list[tuple[str, str, bool]]:
        """Every stored turn, oldest first: (author, text, follows)."""
        rows = scalar(self.url, "SELECT coalesce(string_agg(author || '~' || text || '~' || follows::text, '|' "
                                "ORDER BY id), '') FROM turns")
        out: list[tuple[str, str, bool]] = []
        for row in str(rows).split("|"):
            if row:
                author, text, follows = row.split("~")
                out.append((author, text, follows == "true"))
        return out

    def hers(self) -> list[tuple[str, bool]]:
        return [(text, follows) for author, text, follows in self.turns() if author == "ashley"]

    def work(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM turn_work"))


@pytest.fixture
def model() -> Generator[Model]:
    """A scripted model registered as the locator's inference, for driving `tool_loop` directly."""
    made = Model()
    services.register(Inference, made)
    yield made
    services.unregister(Inference)


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    made = World(db_url, who, Pod(Model(), Lamp()), Pod(Model(), Lamp()))
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    yield made
    for interface in (People, Presence, Inference, Tools):
        services.unregister(interface)


@asynccontextmanager
async def database(w: World) -> AsyncGenerator[PoolDatabase]:
    """Conversations and InFlight on the test's database."""
    db = PoolDatabase(w.url, connect_timeout_s=5.0)
    await db.open()
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, claim_s=CLAIM_S))
    try:
        yield db
    finally:
        services.unregister(Conversations)
        services.unregister(InFlight)
        await db.close()


async def settled(w: World, count: int, timeout: float = 5.0) -> None:
    """Wait for the background part of a held turn to store her `count`th turn."""
    async with asyncio.timeout(timeout):
        while len(w.hers()) < count:
            await asyncio.sleep(0.02)


def kill_the_turn() -> int:
    """Cancel every task running the app's own turn code, as a dead pod does; the database's pool is left alone."""
    mine = [t for t in asyncio.all_tasks() if "/ashley/channels/" in _file_of(t)]
    for task in mine:
        task.cancel()
    return len(mine)


def _file_of(task: "asyncio.Task[object]") -> str:
    code = getattr(task.get_coro(), "cr_code", None)
    return str(getattr(code, "co_filename", ""))
