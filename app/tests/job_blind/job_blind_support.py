"""Helpers for the blind ErrandJob tests (`decisions.md`, "What she could not do for want of a source": "The job"):
real Postgres for Errands, Conversations and People, behind a recording subclass of the Errands store; a scripted
Tools and a scripted Inference through the locator. One tick at a time.

Every guess beyond the design is in the ASSUMPTIONS block below and nowhere else; they are listed with the spec
phrase each rests on in `~/scratch/ashley/errands/job-blind/assumptions.txt`."""

import asyncio
from collections.abc import AsyncGenerator, Collection, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any

import psycopg
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.db.pool import PoolDatabase
from ashley.errands.config import CONFIG, ErrandsConfig
from ashley.errands.errands import Errands
from ashley.channels.errand import ErrandJob
from ashley.errands.model import Counts, Errand, Reason, State
from ashley.errands.postgres import PostgresErrands
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.people import People
from ashley.people.postgres import PostgresPeople
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, scalar
from contract.conversations_support import make as make_conversations

# --- ASSUMPTIONS: change here only -------------------------------------------------------------------------------

HOUSE = "house"
SEARCH = "search"
ASKER_NAME = "Pat Asker"
TASK = "errand"
LEASE_NAME = "errands"
# A1 the job's constructor takes the errands tunables: ErrandJob(config)
# A2 one tick is `await job.tick()`; its return value is not relied on
# A3 `job.run` is the lease body (no arguments): tick, then sleep config.tick_s, until cancelled
# A4 `ashley.channels.errand.NAME` is the lease name
# A5 "anything is due" is asked of the real store however the implementation likes; tests drive a real Postgres store
#    and observe the catalogue reads and the claim calls
# A6 the swept count in `errands.tick` is interrupted + expired
# A7 log field names: errand, attempt, reason, tool_calls, duration_ms on the per-errand lines
# A8 the asker's name appears in the system prompt (the errand section "says who asked")
# A9 the person turn and the turns before it are messages; turns after the ask are not
# A10 the job takes its services from the locator: Errands, Tools, Inference, Conversations, People
FIELD_ERRAND = "errand"
FIELD_ATTEMPT = "attempt"
FIELD_REASON = "reason"
FIELD_TOOL_CALLS = "calls"
FIELD_DURATION = "duration_ms"
TICK_FIELDS = ("swept", "claimed", "done", "released", "given_up", "duration_ms")

CONF: ErrandsConfig = replace(CONFIG, tick_s=0.01, batch=2, max_attempts=3, max_age_s=600.0, claim_s=300.0,
                              context_turns=4, max_tool_rounds=2, max_tool_result_chars=4000, tell_max=3)


def job_of(config: ErrandsConfig) -> ErrandJob:
    return ErrandJob(config)


async def tick(job: ErrandJob) -> None:
    await job.tick()


def swept_of(counts: Counts) -> int:
    return counts.interrupted + counts.expired


# --- the scripted world ------------------------------------------------------------------------------------------

ASK = "zq-ask-text-4417"
RESULT_TEXT = "zq-result-text-9021"
TOOL_ARG = "zq-tool-arg-3358"
TOOL_OUT = "zq-tool-out-7710"
SECRETS = (ASK, RESULT_TEXT, TOOL_ARG, TOOL_OUT)
LIST_TOOL = ToolSpec("add_to_list", "add an item to the shopping list", {"type": "object"}, reads=False, outside=False)
INSTRUCTIONS = "zq-catalogue-guidance-5502"
GOOD = Reply(spoken="Added, said.", text=RESULT_TEXT)


def owed_again(source: str = HOUSE) -> Reply:
    """A reply whose `owed` is set: the source went away again."""
    return Reply.model_validate({"spoken": "Still can't.", "text": "Still can't reach it.", "owed": source})


def run(scenario: Coroutine[Any, Any, None], limit: float = 25.0) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, limit)

    asyncio.run(bounded())


class Recording(PostgresErrands):
    """The real store, recording each call the job makes to it."""

    def __init__(self, database: PoolDatabase) -> None:
        super().__init__(database)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def named(self, name: str) -> list[tuple[Any, ...]]:
        return [args for n, args in self.calls if n == name]

    async def claim(self, answering: Collection[str], max_age_s: float) -> Errand | None:
        self.calls.append(("claim", (frozenset(answering), max_age_s)))
        return await super().claim(answering, max_age_s)

    async def release(self, errand_id: int, attempt: int, max_attempts: int) -> State:
        self.calls.append(("release", (errand_id, attempt, max_attempts)))
        return await super().release(errand_id, attempt, max_attempts)

    async def finish(self, errand_id: int, attempt: int, result: str) -> None:
        self.calls.append(("finish", (errand_id, attempt, result)))
        await super().finish(errand_id, attempt, result)

    async def give_up(self, errand_id: int, attempt: int, reason: Reason) -> None:
        self.calls.append(("give_up", (errand_id, attempt, reason)))
        await super().give_up(errand_id, attempt, reason)

    async def sweep(self, claim_s: float, max_age_s: float) -> Counts:
        self.calls.append(("sweep", (claim_s, max_age_s)))
        return await super().sweep(claim_s, max_age_s)


@dataclass
class FakeTools(Tools):
    """`catalogue` answers `offer` (or raises it when an exception); every call is run and recorded."""

    offer: Catalogue | Exception = field(default_factory=lambda: Catalogue((LIST_TOOL,), INSTRUCTIONS))
    reads: int = 0
    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        self.reads += 1
        if isinstance(self.offer, Exception):
            raise self.offer
        return self.offer

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, TOOL_OUT)


def unreachable(*keys: str) -> Catalogue:
    return Catalogue((LIST_TOOL,), INSTRUCTIONS, tuple(keys))


def use_list(call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, LIST_TOOL.name, {"item": TOOL_ARG}),))


class Hang(Exception):
    """A step scripted as `Hang()` waits until its runner is cancelled."""


@dataclass
class Model(Inference):
    """Answers each step from `script` whatever the tool choice (a script entry that is an Exception is raised); a step
    past the script answers GOOD, so an extra call shows in `prompts`, not as an exception the job might swallow."""

    script: list[ToolCalls | Reply | Exception] = field(default_factory=list[ToolCalls | Reply | Exception])
    prompts: list[Prompt] = field(default_factory=list[Prompt])
    tasks: list[str] = field(default_factory=list[str])
    conversations: list[int | None] = field(default_factory=list[int | None])
    hanging: asyncio.Event = field(default_factory=asyncio.Event)

    def play(self, *script: ToolCalls | Reply | Exception) -> None:
        self.script = list(script)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.prompts.append(prompt)
        self.tasks.append(task)
        self.conversations.append(conversation_id)
        got = self.script.pop(0) if self.script else GOOD
        if isinstance(got, Hang):
            self.hanging.set()
            await asyncio.Event().wait()
        if isinstance(got, Exception):
            raise got
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("an errand steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")

    def system_text(self, step: int = 0) -> str:
        return " ".join(s.text for s in self.prompts[step].system.values())

    def message_texts(self, step: int = 0) -> list[str]:
        return [m.text for m in self.prompts[step].messages if isinstance(m, Message)]


@dataclass
class World:
    url: str
    errands: Recording
    tools: FakeTools
    model: Model
    job: ErrandJob
    config: ErrandsConfig
    hid: int
    asker: int
    conv: int

    def say(self, text: str, author: str = "person", visibility: str = "shared") -> int:
        speaker = self.asker if author == "person" else None
        return int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                                    "visibility) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                          (self.conv, self.hid, author, speaker, text, visibility)))

    async def owe(self, source: str = HOUSE, visibility: str = "shared", text: str = ASK) -> int:
        """A person turn saying `text`, and the errand owed for it."""
        turn = self.say(text, visibility=visibility)
        return await self.errands.owe(self.hid, self.asker, self.conv, turn, source)

    async def owe_many(self, n: int, source: str = HOUSE) -> list[int]:
        return [await self.owe(source) for _ in range(n)]

    async def tick(self) -> None:
        await tick(self.job)

    def forget_calls(self) -> None:
        self.errands.calls.clear()

    def states(self, *ids: int) -> list[str]:
        return [state_of(self.url, i) for i in ids]


@asynccontextmanager
async def opened(url: str, config: ErrandsConfig = CONF) -> AsyncGenerator[World]:
    database = PoolDatabase(url)
    await database.open()
    try:
        hid = household(url, "home")
        asker = person(url, hid, ASKER_NAME)
        conv = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                          (hid,)))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                         "VALUES (%s, %s, %s)", (conv, hid, asker))
        errands, tools, model = Recording(database), FakeTools(), Model()
        services.register(Errands, errands)
        services.register(Tools, tools)
        services.register(Inference, model)
        services.register(Conversations, make_conversations(database, POLICY))
        services.register(People, PostgresPeople(database))
        yield World(url, errands, tools, model, job_of(config), config, hid, asker, conv)
    finally:
        await database.close()


def scenario(url: str, body: Any, config: ErrandsConfig = CONF) -> None:
    """Run `body(world)` against a fresh world on this database."""

    async def go() -> None:
        async with opened(url, config) as w:
            await body(w)

    run(go())


# --- raw rows ----------------------------------------------------------------------------------------------------


def row(url: str, errand: int) -> dict[str, Any]:
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute("SELECT * FROM errands WHERE id = %s", (errand,))
        names = [c.name for c in cur.description or ()]
        found = cur.fetchone()
    assert found is not None, f"no errand {errand}"
    return dict(zip(names, found, strict=True))


def state_of(url: str, errand: int) -> str:
    return str(scalar(url, "SELECT state FROM errands WHERE id = %s", (errand,)))


def set_attempts(url: str, errand: int, attempts: int) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE errands SET attempts = %s WHERE id = %s", (attempts, errand))


def age_created(url: str, errand: int, seconds: float) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE errands SET created_at = created_at - make_interval(secs => %s) WHERE id = %s",
                     (seconds, errand))


def age_claimed(url: str, errand: int, seconds: float) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE errands SET claimed_at = claimed_at - make_interval(secs => %s) WHERE id = %s",
                     (seconds, errand))


def fact_count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM facts"))
