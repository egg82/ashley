"""Fakes for the errands job tests: an in-memory `Errands`, a scripted `Inference` whose replies come back as given,
and the turn-loop fakes for people, conversations and tools, all wired through the locator."""

from collections.abc import Collection, Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TypeVar

import pytest
from ashley import services
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import NewTurn
from ashley.errands.config import CONFIG, ErrandsConfig
from ashley.errands.errands import Errands, ErrandsUnavailable
from ashley.channels.errand.job import ErrandJob
from ashley.errands.model import Counts, Done, Errand, Reason, State
from ashley.inference.inference import Inference
from ashley.inference.model import Prompt, Task, ToolCalls
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.people import People
from ashley.tools.tools import Catalogue, Tools
from contract.turns_support import ALANA, HOUSE, FakeConversations, FakePeople, FakeTools, SPEC
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


@dataclass
class Row:
    errand: Errand
    state: State = "due"
    reason: Reason | None = None
    result: str | None = None


class FakeErrands(Errands):
    """The errand table in memory: `rows` by id, every settle call recorded in `calls`; `down` makes every call raise."""

    def __init__(self) -> None:
        self.rows: dict[int, Row] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.down = False
        self.swept = Counts(0, 0)

    def add(self, errand_id: int, conversation_id: int, turn_id: int, source: str = "house", attempt: int = 0) -> None:
        self.rows[errand_id] = Row(Errand(errand_id, HOUSE, ALANA.id, conversation_id, turn_id, source, attempt,
                                          "shared"))

    def _check(self, name: str, *args: object) -> None:
        self.calls.append((name, args))
        if self.down:
            raise ErrandsUnavailable("down")

    async def owe(self, household_id: int, asker_id: int, conversation_id: int, turn_id: int, source: str) -> int:
        raise AssertionError("the job does not owe")

    async def claim(self, answering: Collection[str], max_age_s: float) -> Errand | None:
        self._check("claim", tuple(answering))
        for row in self.rows.values():
            if row.state == "due" and row.errand.source in answering:
                row.state = "running"
                row.errand = replace(row.errand, attempt=row.errand.attempt + 1)
                return row.errand
        return None

    async def due_sources(self, max_age_s: float) -> frozenset[str]:
        self._check("due_sources", max_age_s)
        return frozenset(r.errand.source for r in self.rows.values() if r.state == "due")

    async def release(self, errand_id: int, attempt: int, max_attempts: int) -> State:
        self._check("release", errand_id, attempt, max_attempts)
        row = self.rows[errand_id]
        if row.state == "running" and row.errand.attempt == attempt:
            row.state, row.reason = ("given_up", "attempts") if attempt >= max_attempts else ("due", None)
        return row.state

    async def finish(self, errand_id: int, attempt: int, result: str) -> None:
        self._check("finish", errand_id, attempt, result)
        self.rows[errand_id].state, self.rows[errand_id].result = "done", result

    async def give_up(self, errand_id: int, attempt: int, reason: Reason) -> None:
        self._check("give_up", errand_id, attempt, reason)
        self.rows[errand_id].state, self.rows[errand_id].reason = "given_up", reason

    async def sweep(self, claim_s: float, max_age_s: float) -> Counts:
        self._check("sweep", claim_s, max_age_s)
        return self.swept

    async def untold(self, hearer: int, limit: int, owner_only: bool = True) -> tuple[Done, ...]:
        raise AssertionError("the job does not tell")

    async def told(self, errand_ids: Collection[int]) -> None:
        raise AssertionError("the job does not tell")


class ScriptedInference(Inference):
    """Answers each `step` with the next scripted outcome as given (no validation); an exception is raised."""

    def __init__(self) -> None:
        self.script: list[Reply | ToolCalls | Exception] = []
        self.asked: list[tuple[Task, Prompt]] = []

    async def generate(self, task: Task, prompt: Prompt, output: type[T], *, conversation_id: int | None = None) -> T:
        raise AssertionError("an errand uses step")

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.asked.append((task, prompt))
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, ToolCalls) or isinstance(outcome, output):
            return outcome
        return output.model_validate(outcome.model_dump())

    async def transcribe(self, task: SpeechTask, heard: Heard, *, conversation_id: int | None = None) -> Transcript:
        raise AssertionError("an errand does not listen")

    async def speak(self, task: SpeechTask, text: str, *, conversation_id: int | None = None) -> Speech:
        raise AssertionError("an errand does not speak")


@dataclass
class World:
    errands: FakeErrands
    tools: FakeTools
    inference: ScriptedInference
    conversations: FakeConversations
    conversation_id: int = 0
    turn_id: int = 0
    config: ErrandsConfig = field(default_factory=lambda: CONFIG)

    def job(self, config: ErrandsConfig | None = None) -> ErrandJob:
        return ErrandJob(config or self.config, now=lambda: NOW, clock=lambda: 0.0)

    def owe(self, errand_id: int = 1, source: str = "house") -> None:
        self.errands.add(errand_id, self.conversation_id, self.turn_id, source)


@pytest.fixture
def world() -> Generator[World]:
    errands, tools, inference = FakeErrands(), FakeTools(), ScriptedInference()
    conversations = FakeConversations()
    cid = conversations.seed("web:1", "chat", [NewTurn("person", "hi", ALANA.id), NewTurn("ashley", "hello"),
                                               NewTurn("person", "put milk on the list", ALANA.id)])
    asked = conversations.stored[cid].turns[-1].id
    services.register(Errands, errands)
    services.register(Tools, tools)
    services.register(Inference, inference)
    services.register(Conversations, conversations)
    services.register(People, FakePeople())
    yield World(errands, tools, inference, conversations, cid, asked)
    services.clear()


def reply(text: str = "I put milk on the list.") -> Reply:
    return Reply(spoken=text, text=text)


def sources(unreachable: tuple[str, ...] = ()) -> Catalogue:
    return Catalogue((SPEC,), "use the lights tool", unreachable)
