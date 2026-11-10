"""The world of the blind taint tests that need a database: real Conversations and PostgresInFlight, a fake model that
records the checkpoint stored at each of its steps, fake tools (`taint_fields_blind_support.SPECS`), and orphaned
checkpoints as a killed runner leaves them. Guesses are in `taint_fields_blind_support.ASSUMPTIONS`."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.channels import checkpoint as checkpoint_module
from ashley.channels.checkpoint import Checkpoint, dumps
from ashley.channels.model import Inbound
from ashley.channels.model import Taint as Origin
from ashley.channels.tool_loop import Progress
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person
from taint_fields_blind_support import SPECS, result_of

DONE = Reply(spoken="Done.", text="Done.")
SYSTEM = SystemPrompt("system from the checkpoint", "moment from the checkpoint")
Taint = str | None


def stored(url: str) -> Checkpoint | None:
    """The checkpoint now stored for the one turn with work; None when there is no work."""
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(b"SELECT checkpoint FROM turn_work ORDER BY said_id DESC LIMIT 1").fetchone()
    return None if row is None else checkpoint_module.loads(row[0])


@dataclass
class Model(Inference):
    """Answers each step from `script`; `seen` is the checkpoint stored when each step was asked, and `prompts` what
    each step was sent."""

    url: str
    script: list[ToolCalls | Reply | Exception] = field(default_factory=list[ToolCalls | Reply | Exception])
    seen: list[Checkpoint | None] = field(default_factory=list[Checkpoint | None])
    prompts: list[Prompt] = field(default_factory=list[Prompt])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.seen.append(stored(self.url))
        self.prompts.append(prompt)
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


@dataclass
class Switchboard(Tools):
    """`ran` is every call that reached a tool."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue(SPECS, "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return result_of(call.id, call.name)


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


def asking(*calls: tuple[str, str], text: str = "look around") -> Progress:
    """A round in flight with no results: the calls asked, as (id, tool)."""
    return Progress((Message("person", text),), 0, len(calls),
                    ToolCalls(tuple(ToolCall(i, name, {"call": i}) for i, name in calls)))


def calls(*names: str) -> ToolCalls:
    """The model asking for each of `names` in one round, under ids c1, c2, ..."""
    return ToolCalls(tuple(ToolCall(f"c{n}", name, {"n": n}) for n, name in enumerate(names, 1)))


@dataclass
class World:
    url: str
    home: int
    who: int
    conversations: Conversations
    inflight: InFlight
    model: Model
    tools: Switchboard

    def inbound(self, thread: str = "web:1", text: str = "look around", taint: Origin | None = None) -> Inbound:
        """A person's own message on their page, a checkpointed turn; `taint` is its origin."""
        return Inbound(self.home, thread, text, "chat", "text", "owner", self.who, False, None, "web", later=True,
                       later_by="turn", opens_benches=True, on_page=True, taint=taint)

    async def orphan(self, progress: Progress | None = None, *, tainted: Taint = None, taint: Origin | None = None,
                     thread: str = "web:1", text: str = "look around") -> Claim:
        """Work begun and abandoned by a runner that was killed: its checkpoint saved, its claim run out."""
        conv = await self.conversations.for_thread(self.home, thread, "chat", [self.who])
        said = await self.conversations.add_turn(conv.id, NewTurn("person", text, self.who))
        start = progress or Progress((Message("person", text),), 0, 0)
        saved = Checkpoint(self.inbound(thread, text, taint), conv.id, said.id, self.who, {"default": SYSTEM}, start,
                           tainted=tainted)
        claim = await self.inflight.begin(conv.id, said.id, dumps(saved))
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(b"UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second' "
                         b"WHERE said_id = %s", (claim.said_id,))
        return claim

    def tainted_at_each_step(self) -> list[Taint | str]:
        """`Checkpoint.tainted` as stored at each model step; 'NO WORK' for a step asked with no work stored."""
        return ["NO WORK" if c is None else c.tainted for c in self.model.seen]


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    who_id = person(url, home)
    conversations, inflight = PostgresConversations(db, POLICY), PostgresInFlight(db, POLICY, 60.0)
    model, tools = Model(url), Switchboard()
    services.register(People, OnePerson(Household(home, "home", "America/Denver", "", (Person(who_id, home, "Alana"),))))
    services.register(Presence, Nobody())
    services.register(Conversations, conversations)
    services.register(InFlight, inflight)
    services.register(Tools, tools)
    services.register(Inference, model)
    try:
        yield World(url, home, who_id, conversations, inflight, model, tools)
    finally:
        for interface in (People, Presence, Conversations, InFlight, Tools, Inference):
            services.unregister(interface)
        await db.close()


def results_sent(prompt: Prompt) -> dict[str, ToolResult]:
    return {r.call_id: r for e in prompt.messages if isinstance(e, ToolResults) for r in e.results}


@pytest.fixture(autouse=True)
def system_comes_from_the_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(*_: object, **__: object) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt("system rebuilt by the persona")}

    monkeypatch.setattr(persona, "system", built)
