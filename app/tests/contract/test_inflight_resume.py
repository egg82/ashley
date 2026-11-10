"""Work in flight survives its pod (`decisions.md`): a web chat turn whose runner is killed mid-turn, after a change
ran, is resumed by another runner (`ashley.channels.resume.sweep`) from its checkpoint in Postgres. The person gets
exactly one reply, stored as her turn on the thread; the change ran once; a change started and never finished is not
run again. Postgres is real (Conversations and `InFlight`); the model, the tools and the people are fakes.

A kill is a cancel of the turn's task with no cleanup of our own; the claim then runs out by the database's clock."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest
from ashley import services
from ashley.api.chat import inbound_from
from ashley.api.models import ChatRequest
from ashley.channels import resume
from ashley.live.events import HerState, TurnFailed
from ashley.live.live import Live
from ashley.channels.model import Inbound
from ashley.channels.respond import RespondUnavailable, respond
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import Kind, NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from ashley.inference.inference import Inference
from ashley.inference.speech import Heard, Speech, SpeechTask, Transcript
from ashley.inference.model import Prompt, SystemPrompt, Task, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.persona import persona
from ashley.senses.presence import Presence
from ashley.signin.model import SignedIn
from ashley.tools.tools import Catalogue, Tools
from live_support import FakeLive
from conversations_support import POLICY, household, person, closing_first, run, scalar
from inflight_outage_support import Outage

CLAIM_S = 0.3
SWITCH = ToolSpec("switch_on", "turn something on", {"type": "object"}, reads=False)
DONE = Reply(spoken="The lamp is on.", text="The lamp is on.")


class Never(Exception):
    """Raised by nothing: a step scripted as `HANG` waits until its runner is killed."""


HANG = Never()


@dataclass
class ScriptedInference(Inference):
    """Answers each step from `script` in order; `HANG` waits forever. `prompts` is what each step was sent."""

    script: list[ToolCalls | Reply | Never] = field(default_factory=list[ToolCalls | Reply | Never])
    prompts: list[Prompt] = field(default_factory=list[Prompt])
    asked: asyncio.Event = field(default_factory=asyncio.Event)

    async def step(self, task: Task, prompt: Prompt, output: type[Any], *,
                   conversation_id: int | None = None) -> Any:
        self.prompts.append(prompt)
        got = self.script.pop(0)
        if got is HANG:
            self.asked.set()
            await asyncio.Event().wait()
        assert not isinstance(got, Never)
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
    """One change tool. `ran` is every call that reached it; with `hang`, a call waits forever once recorded."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])
    hang: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)
    after: Callable[[], None] = lambda: None

    async def catalogue(self) -> Catalogue:
        return Catalogue((SWITCH,), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        self.reached.set()
        self.after()
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
    """What one runner sees: its own model and tools, the shared database behind Conversations and InFlight."""

    inference: ScriptedInference
    tools: Switch


@dataclass
class World:
    url: str
    who: Person
    first: Pod
    second: Pod

    def inbound(self) -> Inbound:
        return inbound_from(SignedIn(1, self.who), ChatRequest(text="turn on the lamp"))

    def as_pod(self, pod: Pod) -> None:
        services.register(Inference, pod.inference)
        services.register(Tools, pod.tools)

    def hers(self) -> list[str]:
        got = scalar(self.url, "SELECT coalesce(string_agg(text, '|' ORDER BY id), '') FROM turns "
                               "WHERE author = 'ashley'")
        return [t for t in str(got).split("|") if t]


def switch_on(call_id: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(call_id, SWITCH.name, {"what": "lamp", "aside": "Turning it on."}),))


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> None:
    def built(kind: Kind, context: persona.Context) -> Mapping[str, SystemPrompt]:
        return {"default": SystemPrompt(f"system for {kind}")}

    monkeypatch.setattr(persona, "system", built)


@pytest.fixture
def world(db_url: str, system: None) -> Generator[World]:
    house = household(db_url)
    who = Person(person(db_url, house, "Alana"), house, "Alana")
    made = World(db_url, who, Pod(ScriptedInference(), Switch()), Pod(ScriptedInference(), Switch()))
    services.register(People, OnePerson(Household(house, "home", "America/Denver", "", (who,))))
    services.register(Presence, Nobody())
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


async def sweep() -> int:
    return await resume.sweep()


async def killed(world: World, reached: asyncio.Event) -> None:
    """The first pod runs the turn until `reached`, then dies without cleaning up."""
    world.as_pod(world.first)
    turn = asyncio.create_task(respond(world.inbound()))
    await asyncio.wait_for(reached.wait(), 5)
    turn.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn


def _results(prompt: Prompt) -> list[ToolResult]:
    return [r for entry in prompt.messages if isinstance(entry, ToolResults) for r in entry.results]


def test_a_turn_killed_after_its_change_is_resumed_once_with_one_reply(world: World) -> None:
    world.first.inference.script = [switch_on(), HANG]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with database(world):
            await killed(world, world.first.inference.asked)
            assert world.hers() == []
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1
            assert await sweep() == 0

    run(go())
    assert world.hers() == [DONE.text]
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []
    (resumed,) = world.second.inference.prompts
    assert [r.content for r in _results(resumed)] == ['{"on": true}']


def test_a_change_started_and_never_finished_is_not_run_again(world: World) -> None:
    world.first.inference.script = [switch_on()]
    world.first.tools.hang = True
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with database(world):
            await killed(world, world.first.tools.reached)
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    assert world.hers() == [DONE.text]
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []
    (resumed,) = world.second.inference.prompts
    (result,) = _results(resumed)
    assert result.is_error


def test_a_turn_whose_runner_is_alive_is_not_taken(world: World) -> None:
    world.first.inference.script = [switch_on(), HANG]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            turn = asyncio.create_task(respond(world.inbound()))
            await asyncio.wait_for(world.first.inference.asked.wait(), 5)
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await sweep() == 0
            turn.cancel()

    run(go())
    assert world.hers() == []


def test_an_outage_mid_turn_answers_pending_and_the_resumed_turn_gives_the_one_reply(world: World) -> None:
    world.first.inference.script = [switch_on(), DONE]
    world.second.inference.script = [DONE]

    async def go() -> None:
        async with database(world):
            outage = Outage(services.get(InFlight))
            services.register(InFlight, outage)
            world.first.tools.after = lambda: setattr(outage, "down", True)
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert (out.follows, out.body) == (True, "")
            assert world.hers() == []
            outage.down = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    run(go())
    assert world.hers() == [DONE.text]
    assert len(world.first.tools.ran) == 1 and world.second.tools.ran == []


def test_a_reply_that_cannot_be_stored_is_never_sent_and_its_work_is_not_resumed(world: World) -> None:
    world.first.inference.script = [DONE]
    world.first.inference.step = closing_first(world.url, world.first.inference.step)

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            with pytest.raises(RespondUnavailable):
                await respond(world.inbound())
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 0

    run(go())
    assert world.hers() == []
    assert world.second.inference.prompts == []


def test_an_orphans_age_counts_from_when_the_person_spoke(world: World) -> None:
    async def go() -> None:
        async with database(world):
            conversations = services.get(Conversations)
            started = await conversations.start(world.who.household_id, "chat", [world.who.id])
            said = await conversations.add_turn(started.id, NewTurn("person", "hello", world.who.id, "private",
                                                                    world.who.id))
            scalar(world.url, "UPDATE turns SET at = at - interval '100 seconds' WHERE id = %s RETURNING id",
                   (said.id,))
            await services.get(InFlight).begin(started.id, said.id, "{}")
            await asyncio.sleep(CLAIM_S * 1.5)
            (orphan,) = await services.get(InFlight).orphaned(10)
            assert orphan.age_s >= 100

    run(go())


def test_a_pending_turn_whose_resume_gives_up_shows_one_failure_and_her_idle(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.first.inference.script = [switch_on(), DONE]
    live = FakeLive()
    monkeypatch.setattr(resume, "CONFIG", resume.Config(CLAIM_S, 1.0, 1, 10))

    async def go() -> None:
        async with database(world):
            services.register(Live, live)
            outage = Outage(services.get(InFlight))
            services.register(InFlight, outage)
            world.first.tools.after = lambda: setattr(outage, "down", True)
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert out.follows
            outage.down = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1

    try:
        run(go())
    finally:
        services.unregister(Live)
    states = [e for e in live.published if isinstance(e, HerState)]
    (thinking,) = {e.turn for e in states if e.state == "thinking"}
    assert [e.state for e in states if e.turn == thinking][-1] == "idle"
    failed = [e for e in live.published if isinstance(e, TurnFailed)]
    assert len(failed) == 1
    assert all(e.shown.person_id == world.who.id for e in [*states, *failed])
    assert world.hers() == [] and world.second.inference.prompts == []
