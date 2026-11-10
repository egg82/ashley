"""Support for the no-silent-endings tests: a scripted model that can fail a step and records the task and prompt of
each, one change tool, and web chat turns over real Conversations and PostgresInFlight. A kill is a cancel of the
turn's task; its claim then runs out by the database's clock."""

import asyncio
import json
from collections.abc import AsyncGenerator, Generator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from importlib import resources
from typing import Any

import pytest
from ashley import logs, services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.limits import Limits
from ashley.channels.model import Inbound, Medium
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference, InferenceError
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.signin.model import SignedIn
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, scalar

CLAIM_S = 0.3
_UNSAID = json.loads(resources.files("ashley.channels").joinpath("unsaid.json").read_text())
LINE: str = _UNSAID["line"]
UNREACHABLE: str = _UNSAID["unreachable"]
WRAP_UP: str = _UNSAID["wrap_up"]
SWITCH = ToolSpec("switch_on", "turn something on", {"type": "object"}, reads=False)
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
GOOD = Reply(spoken="The lamp is on, said.", text="The lamp is on, written.")
WRAPPED = Reply(spoken="Wrapped, said.", text="Wrapped, written.")
HISTORY: tuple[Message, ...] = (Message("person", "turn on the lamp"),)
SYSTEM: Mapping[str, SystemPrompt] = {"default": SystemPrompt("system for chat")}


def limits(rounds: int = 6) -> Limits:
    return Limits(rounds, 8000, 1, 0)


def switch_on(call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, SWITCH.name, {"what": "lamp", "aside": "Turning it on."}),))


Scripted = ToolCalls | Reply | InferenceError


@dataclass
class Model(Inference):
    """Answers each step from `script` (an error in it is raised), whatever the tool choice, and keeps what it was
    asked. A step past the script raises, so an extra call is a red test."""

    script: list[Scripted] = field(default_factory=list[Scripted])
    prompts: list[Prompt] = field(default_factory=list[Prompt])
    tasks: list[Task] = field(default_factory=list[Task])

    def play(self, *script: Scripted) -> None:
        self.script = list(script)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.prompts.append(prompt)
        self.tasks.append(task)
        if not self.script:
            raise AssertionError(f"step {len(self.prompts)} was not scripted: the model was asked once too often")
        got = self.script.pop(0)
        if isinstance(got, InferenceError):
            raise got
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")


@dataclass
class Switch(Tools):
    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, '{"on": true}')


@pytest.fixture
def loop(capsys: pytest.CaptureFixture[str]) -> Generator[Model]:
    """A model registered for `tool_loop` calls made directly, and logs to read back."""
    model = Model()
    services.register(Inference, model)
    logs.setup()
    capsys.readouterr()
    yield model
    services.unregister(Inference)


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
class World:
    url: str
    who: Person
    model: Model
    tools: Switch

    def inbound(self, text: str = "turn on the lamp", medium: Medium = "text") -> Inbound:
        return replace(inbound_from(SignedIn(1, self.who), ChatRequest(text=text)), medium=medium)

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

    def queued(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM outbox"))


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    made = World(db_url, who, Model(), Switch())
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    services.register(Inference, made.model)
    services.register(Tools, made.tools)
    yield made
    for interface in (People, Presence, Inference, Tools):
        services.unregister(interface)


@asynccontextmanager
async def database(world: World) -> AsyncGenerator[PoolDatabase]:
    """Conversations and InFlight on the test's database."""
    db = PoolDatabase(world.url, connect_timeout_s=5.0)
    await db.open()
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, claim_s=CLAIM_S))
    try:
        yield db
    finally:
        services.unregister(Conversations)
        services.unregister(InFlight)
        await db.close()


async def settled(world: World, count: int, timeout: float = 5.0) -> None:
    """Wait for the background part of a turn to store her `count`th turn."""
    async with asyncio.timeout(timeout):
        while len(world.hers()) < count:
            await asyncio.sleep(0.02)
