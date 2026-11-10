"""Support for the blind no-silent-endings tests: web chat turns through `respond` over real Conversations and
PostgresInFlight, with a scripted model that records each step and may raise. A killed runner's claim is run out with
SQL, never waited for."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.inflight import Work
from ashley.channels.model import Inbound, Medium
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind, NewTurn, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.live.live import Live
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.signin.model import SignedIn
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, scalar
from live_support import FakeLive

CLAIM_S = 60.0
CHECKING = Reply(answers=False, spoken="Let me check.", text="Let me check.")
DONE = Reply(spoken="The lamp is on.", text="The lamp is on.")
WRAPPED = Reply(spoken="I looked, and found nothing more.", text="I looked, and found nothing more.")


@dataclass
class Model(Inference):
    """Answers each step from `script`, raising an exception scripted; `calls` is every (task, prompt) it was asked."""

    script: list[ToolCalls | Reply | Exception] = field(default_factory=list[ToolCalls | Reply | Exception])
    calls: list[tuple[Task, Prompt]] = field(default_factory=list[tuple[Task, Prompt]])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.calls.append((task, prompt))
        got = self.script.pop(0)
        if isinstance(got, Exception):
            raise got
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")

    def tasks(self) -> list[Task]:
        return [t for t, _ in self.calls]


class NoTools(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((), "")

    async def call(self, call: ToolCall) -> ToolResult:
        raise AssertionError("no tool is offered")


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
    live: FakeLive

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

    async def expire(self) -> None:
        """Run every claim out, by the database's clock."""
        await asyncio.to_thread(sql, self.url, "UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")

    def claim_left_s(self) -> float:
        """Seconds until the one piece of work's claim runs out, by the database's clock."""
        return float(scalar(self.url, "SELECT extract(epoch FROM claimed_until - clock_timestamp()) FROM turn_work"))


def sql(url: str, query: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(query.encode())


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    made = World(db_url, who, Model(), FakeLive())
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    services.register(Inference, made.model)
    services.register(Tools, NoTools())
    services.register(Live, made.live)
    yield made
    for interface in (People, Presence, Inference, Tools, Live):
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


async def until(condition: Callable[[], object], timeout: float = 5.0) -> None:
    """Wait for the background part of a held turn until `condition` holds."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.02)


# --- a Work that records, for `settle` ---------------------------------------------------------------------------


@dataclass
class Recording(Work):
    """A `Work` that records what `settle` asks of it and raises what it is told to."""

    keeps: bool = True
    told: bool = False
    drops_to: bool = True
    say_error: Exception | None = None
    defer_error: Exception | None = None
    said: list[tuple[int, NewTurn]] = field(default_factory=list[tuple[int, NewTurn]])
    deferred: list[float] = field(default_factory=list[float])
    dropped: int = 0
    marked: int = 0

    async def say(self, conversation_id: int, turn: NewTurn) -> Turn:
        if self.say_error is not None:
            raise self.say_error
        self.said.append((conversation_id, turn))
        return Turn(len(self.said), turn.author, None, turn.text, datetime.now(UTC), turn.follows, conversation_id)

    async def drop(self) -> bool:
        self.dropped += 1
        return self.drops_to

    @property
    def retries(self) -> bool:
        return self.keeps

    @property
    def unreachable_told(self) -> bool:
        return self.told

    async def told_unreachable(self) -> None:
        self.marked += 1
        self.told = True

    async def defer(self, seconds: float) -> None:
        if self.defer_error is not None:
            raise self.defer_error
        self.deferred.append(seconds)


# --- InFlight on its own ------------------------------------------------------------------------------------------


@dataclass
class Rig:
    db: PoolDatabase
    url: str
    home: int
    who: int
    conversations: Conversations
    inflight: InFlight

    async def said(self, thread: str = "web:1", text: str = "hello") -> tuple[int, int]:
        """A conversation on `thread` with one person turn in it: (conversation id, that turn's id)."""
        conv = await self.conversations.for_thread(self.home, thread, "chat", [self.who])
        turn = await self.conversations.add_turn(conv.id, NewTurn("person", text, self.who))
        return conv.id, turn.id

    def left_s(self) -> float:
        """Seconds until the one piece of work's claim runs out, by the database's clock."""
        return float(scalar(self.url, "SELECT extract(epoch FROM claimed_until - clock_timestamp()) FROM turn_work"))

    async def expire(self) -> None:
        await asyncio.to_thread(sql, self.url, "UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")


@asynccontextmanager
async def rig(url: str, claim_s: float = CLAIM_S) -> AsyncGenerator[Rig]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        home = household(url)
        conversations = PostgresConversations(db, POLICY)
        inflight = PostgresInFlight(db, POLICY, claim_s)
        services.register(Conversations, conversations)
        services.register(InFlight, inflight)
        yield Rig(db, url, home, person(url, home), conversations, inflight)
    finally:
        services.unregister(Conversations)
        services.unregister(InFlight)
        await db.close()
