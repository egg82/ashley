"""Support for the blind runs-in-history tests: stored-run and turn builders, a Runs that counts its reads, and a
`respond` world over a real Postgres with a model that captures the messages it is sent."""

import asyncio
from collections.abc import AsyncGenerator, Generator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import services
from ashley.channels.limits import Limits
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Author, Kind, Turn
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
from ashley.runs.model import Artifact, BenchRun, NewRun, Outcome, Output, Run
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs, RunsUnavailable
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import POLICY, household, person, scalar

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def limits(carried: int = 3, script: int = 50, output: int = 50) -> Limits:
    return Limits(4, 1000, 10, 0, carried_runs=carried, run_script_chars=script, run_output_chars=output)


def out(stdout: str = "", stderr: str = "", outcome: Outcome = "ran", exit_code: int | None = 0,
        files: Mapping[str, str] | None = None) -> Output:
    return Output(outcome, exit_code, stdout, stderr, False, files or {})


def stored(id: int, turn_id: int | None, script: str = "print(1)", output: Output | None = None, stdin: str = "",
           files: Mapping[str, str] | None = None, bench: BenchRun | None = None) -> Run:
    return Run(id, 1, 1, turn_id, f"call-{id}", "python", script, stdin, files or {}, T0, T0 if output else None,
               output, bench)


def turn(id: int, author: Author = "person", follows: bool = False, conversation: int | None = 1,
         text: str = "words", answers: int | None = None) -> Turn:
    """`answers` is the person turn a turn of hers answers."""
    return Turn(id, author, 7 if author == "person" else None, text, T0 + timedelta(minutes=id), follows, conversation,
                answers)


@dataclass
class CountingRuns(Runs):
    """Hands back `found` from `of_turns` and records each read; raises RunsUnavailable when `broken`."""

    found: list[Run] = field(default_factory=list[Run])
    broken: bool = False
    reads: list[tuple[int, tuple[int, ...], int]] = field(default_factory=list[tuple[int, tuple[int, ...], int]])

    async def of_turns(self, household_id: int, turn_ids: tuple[int, ...], latest: int) -> list[Run]:
        self.reads.append((household_id, turn_ids, latest))
        if self.broken:
            raise RunsUnavailable("down")
        return self.found

    async def start(self, run: NewRun) -> int:
        raise AssertionError("not used")

    async def finish(self, run_id: int, output: Output, artifacts: Sequence[Artifact] = ()) -> Run:
        raise AssertionError("not used")

    async def get(self, household_id: int, run_id: int) -> Run | None:
        raise AssertionError("not used")

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Run]:
        raise AssertionError("not used")

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        raise AssertionError("not used")

    async def files_left(self, household_id: int, bench_id: int, piece_id: int) -> Mapping[str, str]:
        raise AssertionError("not used")


RUN_CODE = ToolSpec("run_code", "run a script", {"type": "object"}, reads=False)


@dataclass
class Capture(Inference):
    """A scripted model that keeps every prompt it was sent."""

    script: list[ToolCalls | Reply] = field(default_factory=list[ToolCalls | Reply])
    prompts: list[Prompt] = field(default_factory=list[Prompt])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.prompts.append(prompt)
        got = self.script.pop(0)
        return got if isinstance(got, ToolCalls) else output.model_validate(got.model_dump())

    async def generate(self, task: Task, prompt: Prompt, output: type[Any], *,
                       conversation_id: int | None = None) -> Any:
        raise AssertionError("a turn steps, it never generates")

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("not used")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("not used")


def calls_run_code(call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, RUN_CODE.name, {"script": "x"}),))


@dataclass
class RunsTool(Tools):
    """`run_code` as the real tool leaves it: a run recorded against the person turn that asked, then finished."""

    url: str
    runs: PostgresRuns
    output: Output
    script: str

    async def catalogue(self) -> Catalogue:
        return Catalogue((RUN_CODE,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        row = scalar(self.url, "SELECT id || ',' || conversation_id || ',' || (SELECT household_id FROM "
                               "conversations c WHERE c.id = conversation_id) FROM turns WHERE author = 'person' "
                               "ORDER BY id DESC LIMIT 1")
        turn_id, conversation, home = (int(x) for x in str(row).split(","))
        run_id = await self.runs.start(NewRun(home, conversation, turn_id, call.id, "python", self.script))
        await self.runs.finish(run_id, self.output)
        return ToolResult(call.id, '{"ok": true}')


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
    model: Capture


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


def build_world(url: str) -> Generator[World]:
    house = household(url)
    who = Person(person(url, house, "Alana"), house, "Alana")
    made = World(url, who, Capture())
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
    services.register(Inference, made.model)
    yield made
    for interface in (People, Presence, Inference, Tools, Runs, Conversations, InFlight):
        services.unregister(interface)


@asynccontextmanager
async def database(world: World) -> AsyncGenerator[PoolDatabase]:
    db = PoolDatabase(world.url, connect_timeout_s=5.0)
    await db.open()
    services.register(Conversations, PostgresConversations(db, POLICY))
    services.register(InFlight, PostgresInFlight(db, POLICY, claim_s=0.3))
    try:
        yield db
    finally:
        await db.close()


def run_async(scenario: Any) -> None:
    asyncio.run(asyncio.wait_for(scenario, 30))
