"""A migrated database with a household, a person, a bench and a turn, and the BenchJobs store over it, for the tests
of bench jobs and of what runs them."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ashley.db.pool import PoolDatabase
from ashley.errands.bench_jobs import BenchJobs, Named, NewJob, Worker
from ashley.errands.bench_jobs_postgres import PostgresBenchJobs
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, scalar


@dataclass(frozen=True)
class Setting:
    url: str
    household: int
    person: int
    bench: int
    conversation: int
    turn: int

    def new(self, worker: Worker = "agent", piece: int = 1, title: str = "t", pieces: tuple[Named, ...] = ()) -> NewJob:
        return NewJob(self.household, self.person, self.bench, self.conversation, self.turn, worker, title, "brief",
                      pieces, piece)


def setting(url: str) -> Setting:
    home = household(url)
    who = person(url, home)
    bench = int(scalar(url, "INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, 'b') RETURNING id",
                       (home, who)))
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'brainstorm') "
                                   "RETURNING id", (home,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                           "VALUES (%s, %s, 'person', %s, 'x', 'private') RETURNING id", (conversation, home, who)))
    return Setting(url, home, who, bench, conversation, turn)


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[BenchJobs]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresBenchJobs(db)
    finally:
        await db.close()


# --- the world a job runs in ---------------------------------------------------------------------------------------

import asyncio
from dataclasses import field
from typing import Any, TypeVar

from ashley import services
from ashley.connections.connections import Connections
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access, BridgeFailed, OutFile, Reason, Screen, Session, SessionList, Status, Whoami
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCall, ToolCalls
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.workshop import Workshop
from bench_run_support import Box, World, world as run_world
from money_support import HeldConnections
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
BRIDGE_URL = "https://127.0.0.1:7843#sha256=" + "0" * 64


class Scripted(Inference):
    """Answers each `step` with the next scripted value (a model, a ToolCalls or an exception) and keeps the prompts."""

    def __init__(self) -> None:
        self.script: list[BaseModel | ToolCalls | Exception] = []
        self.asked: list[tuple[Task, Prompt]] = []
        self.hang = False

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("a job steps")

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.asked.append((task, prompt))
        if self.hang:
            await asyncio.sleep(30)
        got = self.script.pop(0)
        if isinstance(got, Exception):
            raise got
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")


def calls(name: str, arguments: dict[str, Any], call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, name, arguments),))


@dataclass
class FakeBridge(Bridge):
    """A bridge in memory: `capabilities` and `roots` as it reports them, `listed` its sessions, `files` what each
    session's `out/` holds, every call recorded in `log` as (name, session, argument)."""

    capabilities: tuple[str, ...] = ("files",)
    roots: tuple[str, ...] | None = ("/work",)
    listed: dict[str, Session] = field(default_factory=dict[str, Session])
    files: dict[str, dict[str, bytes]] = field(default_factory=dict[str, dict[str, bytes]])
    uploads: dict[str, dict[str, bytes]] = field(default_factory=dict[str, dict[str, bytes]])
    prompts: list[str] = field(default_factory=list[str])
    log: list[tuple[str, str, str]] = field(default_factory=list[tuple[str, str, str]])
    refuse_prompt: Reason | None = None
    down: bool = False
    refuse: Reason | None = None

    def _up(self) -> None:
        if self.refuse is not None:
            raise BridgeFailed(self.refuse)
        if self.down:
            raise BridgeFailed("herdr_unavailable")

    async def whoami(self, access: Access) -> Whoami:
        self._up()
        return Whoami("0.2.0", "1", "1", self.capabilities)

    async def sessions(self, access: Access) -> SessionList:
        self._up()
        return SessionList(tuple(self.listed.values()), None, self.roots)

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        raise AssertionError("not used")

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        self._up()
        self.log.append(("prompt", session_id, ""))
        if self.refuse_prompt is not None:
            raise BridgeFailed(self.refuse_prompt)
        self.prompts.append(text)

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        self._up()
        made = Session(f"00000000-0000-0000-0000-{len(self.listed):012d}", label, directory, "idle", 5, None)
        self.listed[made.id] = made
        self.log.append(("start", made.id, directory))
        return made

    async def close(self, access: Access, session_id: str) -> None:
        self._up()
        self.listed.pop(session_id, None)
        self.log.append(("close", session_id, ""))

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        self._up()
        self.uploads.setdefault(session_id, {})[name] = data
        self.log.append(("upload", session_id, name))

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        self._up()
        return tuple(OutFile(n, len(b)) for n, b in self.files.get(session_id, {}).items())

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        self._up()
        return self.files[session_id][name]

    def state(self, session_id: str, status: Status, seq: int) -> None:
        old = self.listed[session_id]
        self.listed[session_id] = Session(old.id, old.label, old.dir, status, seq, None)


@dataclass
class Jobs:
    """What a job's tests hold: the setting, the run world, the fake bridge and model, the memory store."""

    s: Setting
    run: World
    bridge: FakeBridge
    model: Scripted
    store: MemoryStore

    @property
    def owner(self) -> Owner:
        return Owner(self.s.household, self.s.person)

    async def piece(self, kind: str = "note", title: str = "T", body: str = "body") -> int:
        applied = await services.get(Workshop).apply(self.owner, self.s.bench, Add(By(self.s.person), kind, Text(title, body),
                                                                                  "medium"))
        assert applied.piece_id is not None
        return applied.piece_id


@asynccontextmanager
async def jobs_world(url: str, box: Box | None = None) -> AsyncGenerator[Jobs]:
    s = setting(url)
    async with run_world(url, box) as world:
        db = world.database
        held = HeldConnections()
        held.connect(s.household, BRIDGE_URL, "tok", "herdr", s.person)
        made = Jobs(s, world, FakeBridge(), Scripted(), MemoryStore())
        services.register(Connections, held)
        services.register(Bridge, made.bridge)
        services.register(Inference, made.model)
        services.register(ObjectStore, made.store)
        services.register(Watches, PostgresWatches(db))
        services.register(BenchJobs, PostgresBenchJobs(db))
        try:
            yield made
        finally:
            for interface in (Connections, Bridge, Inference, ObjectStore, Watches, BenchJobs):
                services.unregister(interface)
