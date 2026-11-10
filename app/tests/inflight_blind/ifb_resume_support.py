"""Support for the blind resume tests: real Conversations and PostgresInFlight, fake people, tools and model, and
checkpoints that are orphaned the way a killed runner leaves them."""

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from ashley import services
from ashley.channels.checkpoint import Checkpoint, dumps
from ashley.channels.model import Inbound
from ashley.channels.tool_loop import Progress
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight
from ashley.inference.inference import Inference
from ashley.inference.model import Message, Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.tools.tools import Catalogue, Tools
from ifb_support import Rig, rig

LOOK = ToolSpec("look", "see something", {"type": "object"}, reads=True)
SWITCH = ToolSpec("switch", "turn something on", {"type": "object"}, reads=False)
DONE = Reply(spoken="The lamp is on.", text="The lamp is on.")
SYSTEM = SystemPrompt("system from the checkpoint", "moment from the checkpoint")


@dataclass
class Model(Inference):
    """Answers each step from `script`; `prompts` is what each step was sent."""

    script: list[ToolCalls | Reply | Exception] = field(default_factory=list[ToolCalls | Reply | Exception])
    prompts: list[Prompt] = field(default_factory=list[Prompt])

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
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
        return Catalogue((LOOK, SWITCH), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, f'{{"ran": "{call.name}"}}')


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
    r: Rig
    model: Model
    tools: Switchboard

    async def orphan(self, progress: Progress | None = None, started: frozenset[str] = frozenset(), *,
                     thread: str = "web:1", text: str = "turn on the lamp", raw: str | None = None,
                     later_by: Literal["outbox", "turn"] = "turn") -> Claim:
        """Work begun and abandoned by a runner that was killed: its checkpoint saved, its claim run out."""
        conv_id, said_id = await self.r.said(thread, text)
        start = progress or Progress((Message("person", text),), 0, 0)
        inbound = Inbound(self.r.home, thread, text, "chat", "text", "owner", self.r.who, False, None, "web",
                          later=True, later_by=later_by, opens_benches=True, on_page=True)
        saved = Checkpoint(inbound, conv_id, said_id, self.r.who, {"default": SYSTEM}, start, started)
        claim = await self.r.inflight.begin(conv_id, said_id, dumps(saved) if raw is None else raw)
        await self.r.expire(claim)
        return claim


def asking(*calls: tuple[str, str], text: str = "turn on the lamp",
           done: Mapping[str, ToolResult] | None = None) -> Progress:
    """A round in flight: the calls asked, (id, tool), and the results it already has."""
    return Progress((Message("person", text),), 0, len(calls),
                    ToolCalls(tuple(ToolCall(i, name, {"what": "lamp", "call": i}) for i, name in calls)), dict(done or {}))


def results_sent(prompt: Prompt) -> dict[str, ToolResult]:
    return {r.call_id: r for e in prompt.messages if isinstance(e, ToolResults) for r in e.results}


@asynccontextmanager
async def world(url: str, claim_s: float = 60.0, inflight: InFlight | None = None) -> AsyncGenerator[World]:
    async with rig(url, claim_s) as r:
        who = Person(r.who, r.home, "Alana")
        model, tools = Model(), Switchboard()
        services.register(People, OnePerson(Household(r.home, "home", "America/Denver", "", (who,))))
        services.register(Presence, Nobody())
        services.register(Conversations, r.conversations)
        services.register(InFlight, inflight or r.inflight)
        services.register(Tools, tools)
        services.register(Inference, model)
        try:
            yield World(r, model, tools)
        finally:
            for interface in (People, Presence, Conversations, InFlight, Tools, Inference):
                services.unregister(interface)


@pytest.fixture(autouse=True)
def system_comes_from_the_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(*_: object, **__: object) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt("system rebuilt by the persona")}

    monkeypatch.setattr(persona, "system", built)


