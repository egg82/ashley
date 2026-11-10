"""Support for the blind bench-polish tests: bench and chat turns through `respond` over real Conversations, InFlight and
Workshop, with a scripted model whose steps can be hooks. Two pods are two database pools against one Postgres; a pod
is picked per task by `POD`, so a message from "another pod" is a task that sets it. A kill is a cancel of the tasks
running the app's turn code; the work's claim then runs out (set in the past by SQL, no waiting)."""

import asyncio
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar

import psycopg
import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels.model import Inbound, Outbound, on_bench
from ashley.channels.respond import respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight
from ashley.conversations.model import Kind, NewTurn, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.live.live import Live
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from ashley.senses.presence import Presence
from ashley.signin.model import SignedIn
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Bench, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from bench_run_support import Box, Heard as Overheard
from contract.conversations_support import POLICY, household, person, scalar

CLAIM_S = 0.3
POD: ContextVar[int] = ContextVar("pod", default=1)
NOBENCH = Bench(0, 0, 0, "", datetime(2026, 1, 1, tzinfo=UTC), None)
SWITCH = ToolSpec("switch_on", "turn something on", {"type": "object"}, reads=False, outside=False)
T = TypeVar("T")


def reply(text: str, answers: bool = True) -> Reply:
    return Reply(answers=answers, spoken=text, text=text)


def switch_on(call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, SWITCH.name, {"what": "lamp", "aside": "Turning it on."}),))


def move_to(bench_id: int, call_id: str = "m1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, "move_page", {"to": "bench", "bench_id": bench_id, "aside": "Moving."}),))


Step = ToolCalls | Reply | Exception | Callable[[Prompt], Awaitable[ToolCalls | Reply]]


@dataclass
class Model(Inference):
    """Each step pops `script`: a ToolCalls, a Reply, an exception to raise, or an async function of the prompt."""

    script: list[Step] = field(default_factory=list[Step])
    prompts: list[Prompt] = field(default_factory=list[Prompt])
    tasks: list[Task] = field(default_factory=list[Task])

    def play(self, *steps: Step) -> None:
        self.script = list(steps)

    @property
    def steps(self) -> int:
        return len(self.prompts)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *, conversation_id: int | None = None) -> Any:
        self.prompts.append(prompt)
        self.tasks.append(task)
        got = self.script.pop(0)
        if isinstance(got, Exception):
            raise got
        if callable(got):
            got = await got(prompt)
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
    """One change tool; `during` runs inside its first call, a hook for what happens while a round is in flight."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])
    during: Callable[[], Awaitable[None]] | None = None

    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        hook, self.during = self.during, None
        if hook is not None:
            await hook()
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


class FinishHook(PostgresInFlight):
    """The real store, but `before_finish` runs once before a work's final store, and `on_finish` is told each call."""

    before_finish: Callable[[], Awaitable[None]] | None = None

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        hook, self.before_finish = self.before_finish, None
        if hook is not None:
            await hook()
        return await super().finish(claim, turn, after)


def routed(interface: type[T], pods: Mapping[int, Any]) -> T:
    """An `interface` whose every call goes to the implementation of the pod `POD` names in the calling task."""
    abstract: frozenset[str] = getattr(interface, "__abstractmethods__")
    named = set(abstract) | {n for n, v in vars(interface).items() if not n.startswith("_") and not isinstance(v, classmethod)}
    members: dict[str, Any] = {}
    for name in named:
        raw: object = inspect.getattr_static(interface, name)
        if isinstance(raw, property):
            def read(self: Any, _n: str = name) -> Any:
                return getattr(pods[POD.get()], _n)
            members[name] = property(read)
        elif inspect.iscoroutinefunction(raw):
            async def call(self: Any, *a: Any, _n: str = name, **k: Any) -> Any:
                return await getattr(pods[POD.get()], _n)(*a, **k)
            members[name] = call
        else:
            def plain(self: Any, *a: Any, _n: str = name, **k: Any) -> Any:
                return getattr(pods[POD.get()], _n)(*a, **k)
            members[name] = plain
    made: Any = type("Routed", (interface,), members)()
    return made


@dataclass
class World:
    url: str
    who: Person
    bench: Bench
    model: Model
    tools: Switch
    inflight: dict[int, FinishHook]
    box: Box
    heard: Overheard

    def bench_say(self, text: str) -> Inbound:
        return on_bench(self.who.household_id, self.who.id, self.bench.id, text)

    def chat_say(self, text: str) -> Inbound:
        return inbound_from(SignedIn(1, self.who), ChatRequest(text=text))

    async def from_pod(self, pod: int, inbound: Inbound) -> Outbound:
        """`respond` as another pod's request: a task of its own whose pool is that pod's."""
        async def go() -> Outbound:
            POD.set(pod)
            return await respond(inbound)
        return await asyncio.create_task(go())

    async def sweep(self, pod: int) -> int:
        """Another pod's resume sweep: the work whose claim ran out, finished from its checkpoint."""
        from ashley.channels import resume

        async def go() -> int:
            POD.set(pod)
            return await resume.sweep()
        return await asyncio.create_task(go())

    def thread_conversation(self, thread: str) -> int:
        return int(scalar(self.url, "SELECT conversation_id FROM conversation_threads WHERE thread = %s", (thread,)))

    def talk(self, thread: str | None = None) -> list[tuple[str, str, bool]]:
        """A thread's turns, oldest first: (author, text, follows). The bench's talk by default."""
        cid = self.thread_conversation(thread or f"bench:{self.bench.id}")
        rows = scalar(self.url, "SELECT coalesce(string_agg(author || '~' || text || '~' || follows::text, '|' "
                                "ORDER BY id), '') FROM turns WHERE conversation_id = %s", (cid,))
        out: list[tuple[str, str, bool]] = []
        for row in str(rows).split("|"):
            if row:
                author, text, follows = row.split("~", 2)
                out.append((author, text, follows == "true"))
        return out

    def hers(self, thread: str | None = None) -> list[str]:
        return [t for a, t, f in self.talk(thread) if a == "ashley" and not f]

    def work(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM turn_work"))

    def expire_claims(self) -> None:
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(b"UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'")


def said(prompt: Prompt) -> list[str]:
    """The texts of the person messages a prompt carries that her speaker just said, in order."""
    return [e.text for e in prompt.messages if isinstance(e, Message) and e.author == "person"
            and "just said:" in e.text]


def tool_names(prompt: Prompt) -> set[str]:
    return {t.name for t in prompt.tools}


def entries_text(prompt: Prompt) -> list[str]:
    out: list[str] = []
    for e in prompt.messages:
        out.append(e.text if isinstance(e, Message) else type(e).__name__)
    return out


def file_of(task: "asyncio.Task[object]") -> str:
    code = getattr(task.get_coro(), "cr_code", None)
    return str(getattr(code, "co_filename", ""))


def kill_the_turn() -> int:
    """Cancel every task running the app's own turn code (the continuation and its heartbeat), as a dead pod does;
    the database's pools are left alone."""
    mine = [t for t in asyncio.all_tasks() if "/ashley/channels/" in file_of(t)]
    for task in mine:
        task.cancel()
    return len(mine)


async def hang() -> None:
    await asyncio.Event().wait()


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    """Alana, a household of one, and an open bench of his; databases and services are made by `pods`."""
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    box, heard = Box(), Overheard()
    made = World(db_url, who, NOBENCH, Model(), Switch(), {}, box, heard)
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    services.register(Inference, made.model)
    services.register(Tools, made.tools)
    services.register(Sandbox, box)
    services.register(Live, heard)
    yield made
    for interface in (People, Presence, Inference, Tools, Sandbox, Live, Runs, Workshop, Conversations, InFlight):
        services.unregister(interface)


@asynccontextmanager
async def pods(w: World, count: int = 2) -> AsyncGenerator[list[PoolDatabase]]:
    """`count` pods, each with its own pool; the locator's Conversations and InFlight route by `POD`. The world's
    bench is opened through the first."""
    dbs = [PoolDatabase(w.url, connect_timeout_s=5.0) for _ in range(count)]
    for db in dbs:
        await db.open()
    convs = {i + 1: PostgresConversations(db, POLICY) for i, db in enumerate(dbs)}
    w.inflight = {i + 1: FinishHook(db, POLICY, claim_s=CLAIM_S) for i, db in enumerate(dbs)}
    services.register(Conversations, routed(Conversations, convs))
    services.register(InFlight, routed(InFlight, w.inflight))
    workshop = PostgresWorkshop(dbs[0], workshop_rules.load())
    services.register(Workshop, workshop)
    services.register(Runs, PostgresRuns(dbs[0]))
    w.bench = await workshop.open(Owner(w.who.household_id, w.who.id), "scratch")
    try:
        yield dbs
    finally:
        POD.set(1)
        for db in dbs:
            await db.close()


async def finished(w: World, count: int, thread: str | None = None, timeout: float = 5.0) -> None:
    """Wait for the background part of a turn to store her `count`th turn of the thread."""
    async with asyncio.timeout(timeout):
        while int(scalar(w.url, "SELECT count(*) FROM turns t JOIN conversation_threads c ON c.conversation_id = "
                                "t.conversation_id WHERE c.thread = %s AND t.author = 'ashley' AND NOT t.follows",
                         (thread or f"bench:{w.bench.id}",))) < count:
            await asyncio.sleep(0.02)
