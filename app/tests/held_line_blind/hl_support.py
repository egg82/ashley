"""Support for the blind held-line tests: web chat turns through `respond` over real Conversations and PostgresInFlight,
with a scripted model and one change tool. A kill is a cancel of the turn's task; its claim then runs out by the
database's clock."""

import asyncio
from collections.abc import AsyncGenerator, Generator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.model import Inbound
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
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
SWITCH = ToolSpec("switch_on", "turn something on", {"type": "object"}, reads=False)
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
DONE = Reply(spoken="The lamp is on.", text="The lamp is on.")


class Hang(Exception):
    """A step scripted as `HANG` waits until its runner is killed."""


HANG = Hang()


def switch_on(call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, SWITCH.name, {"what": "lamp", "aside": "Turning it on."}),))


@dataclass
class Model(Inference):
    script: list[ToolCalls | Reply | Hang] = field(default_factory=list[ToolCalls | Reply | Hang])
    asked: asyncio.Event = field(default_factory=asyncio.Event)
    steps: int = 0

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.steps += 1
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


@dataclass
class Switch(Tools):
    ran: list[ToolCall] = field(default_factory=list[ToolCall])
    hang: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)

    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        self.reached.set()
        if self.hang:
            await asyncio.Event().wait()
        return ToolResult(call.id, '{"on": true}')


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
    tools: Switch


@dataclass
class World:
    url: str
    who: Person
    first: Pod
    second: Pod

    def inbound(self, text: str = "turn on the lamp") -> Inbound:
        return inbound_from(SignedIn(1, self.who), ChatRequest(text=text))

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
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    made = World(db_url, who, Pod(Model(), Switch()), Pod(Model(), Switch()))
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    yield made
    for interface in (People, Presence, Inference, Tools):
        services.unregister(interface)


@asynccontextmanager
async def database(world: World, inflight: type[InFlight] | None = None) -> AsyncGenerator[PoolDatabase]:
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


async def ended(world: World, timeout: float = 5.0) -> None:
    """Wait for the background part of a held turn to end its work."""
    async with asyncio.timeout(timeout):
        while world.work():
            await asyncio.sleep(0.02)


async def settled(world: World, count: int, timeout: float = 5.0) -> None:
    """Wait for the background part of a held turn to store her `count`th turn."""
    async with asyncio.timeout(timeout):
        while len(world.hers()) < count:
            await asyncio.sleep(0.02)
