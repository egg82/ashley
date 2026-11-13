"""The `wakes` runner over the real turn loop, Conversations, InFlight, Outbox, Workshop and Wakes on one database, with a
scripted model, recorded tools and a person for `person.alana`. A pod is the scripted model and tools `World.as_pod`
selects, as in the work-in-flight suite; a kill cancels the sweep with no cleanup of our own."""

import json
from typing import Any
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg
from ashley import services
from ashley.channels.outbox import Outbox
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.channels.wake import runner
from ashley.initiative.initiative import Initiative
from initiative_support import speaking
from ashley.inference.model import Prompt, ToolCall, ToolCalls, ToolResult, ToolResults, ToolSpec
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.people.model import Household, Person
from ashley.people.people import People, PeopleUnavailable
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Wakes
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, scalar
from contract.test_inflight_resume import OnePerson, World, database
from live_support import FakeLive
from wb_support import add_device, wake

ALLOWED = ToolSpec("lamp_on", "turn the lamp on", {"type": "object"}, reads=False, outside=False)
FORBIDDEN = ToolSpec("garage_open", "open the garage", {"type": "object"}, reads=False, outside=False)
GREET = "Say hello and nothing else, PLANTED-BRIEF-zq."
DONE = Reply(spoken="Welcome home.", text="Welcome home.")
SILENT = Reply(spoken="Nothing to say.", text="Nothing to say.", says="none")


@dataclass
class House(Tools):
    """Two change tools; `ran` is every call that reached one."""

    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue((ALLOWED, FORBIDDEN), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, '{"ok": true}')


@dataclass
class HaPeople(OnePerson):
    """`person.alana` (or `alana`) is the world's person."""

    who: Person | None = None
    down: bool = False

    async def person_for(self, system: str, external_id: str) -> Person | None:
        if self.down:
            raise PeopleUnavailable("down")
        if external_id == "person.kim":
            return Person(900, self.home.id + 1, "Kim")
        return self.who if external_id in ("person.alana", "alana", None) else None


def call(name: str, id_: str = "c1") -> ToolCalls:
    return ToolCalls((ToolCall(id_, name, {}),))


def results(prompt: Prompt) -> list[ToolResult]:
    return [r for e in prompt.messages if isinstance(e, ToolResults) for r in e.results]


def seen_by_model(prompt: Prompt) -> str:
    return repr(prompt.messages) + repr(prompt.system)


@dataclass
class Stack:
    world: World
    device: int
    workshop: Workshop
    wakes: Wakes

    @property
    def owner(self) -> Owner:
        return Owner(self.world.who.household_id, self.world.who.id)

    async def rule(self, event: str = "arrived", brief: str = GREET, tools: tuple[str, ...] = ("lamp_on",),
                   body: str | None = None, greets: bool | None = None) -> int:
        bench = await self.workshop.open(self.owner, "wakes")
        fields: dict[str, object] = {"event": event, "brief": brief, "tools": list(tools)}
        if greets is not None:
            fields["greets"] = greets
        text = body if body is not None else json.dumps(fields)
        applied = await self.workshop.apply(self.owner, bench.id, Add(By(self.world.who.id), "wake", Text("rule", text), "small"))
        assert applied.outcome == "accepted", applied
        return bench.id

    async def hand_in(self, event_id: str = "ctx-1", event: str = "arrived", who: str | None = "person.alana",
                      what: str | None = None) -> int:
        got = await self.wakes.receive(self.device, wake(self.world.who.household_id, event_id, event, who, what,
                                                         at=_now()))
        return got.id

    def outcome(self, wake_id: int) -> object:
        return scalar(self.world.url, "SELECT outcome FROM wakes WHERE id = %s", (wake_id,))

    def exists(self, wake_id: int) -> bool:
        return int(scalar(self.world.url, "SELECT count(*) FROM wakes WHERE id = %s", (wake_id,))) == 1

    def age(self, wake_id: int, seconds: float) -> None:
        with psycopg.connect(self.world.url, autocommit=True) as conn:
            conn.execute("UPDATE wakes SET received_at = received_at - make_interval(secs => %s), "
                         "due_at = due_at - make_interval(secs => %s) WHERE id = %s", (seconds, seconds, wake_id))

    def turns_of(self, wake_id: int) -> int:
        return int(scalar(self.world.url, "SELECT count(*) FROM turns WHERE source = %s", (f"wake:{wake_id}",)))

    def queued(self) -> int:
        return int(scalar(self.world.url, "SELECT count(*) FROM outbox"))

    def hers(self) -> list[str]:
        return self.world.hers()


def _now() -> datetime:
    return datetime.now(UTC)


@asynccontextmanager
async def stack(world: World, initiative: Initiative | None = None) -> AsyncGenerator[Stack]:
    async with database(world) as db:
        wakes = PostgresWakes(db)
        workshop = PostgresWorkshop(db, workshop_rules.load())
        services.register(Wakes, wakes)
        services.register(Workshop, workshop)
        services.register(Live, FakeLive())
        services.register(Outbox, PostgresOutbox(db, 600.0, POLICY))
        services.register(Initiative, initiative or speaking())
        services.register(People, HaPeople(Household(world.who.household_id, "home", "America/Denver", "", (world.who,)),
                                           who=world.who))
        for pod in (world.first, world.second):
            holder: Any = pod
            holder.tools = House()
        world.as_pod(world.first)
        yield Stack(world, add_device(world.url, world.who.household_id, "wb-ha-token"), workshop, wakes)


async def sweep() -> int:
    return await runner.sweep()


def ran(pod: object) -> list[ToolCall]:
    """The tool calls the pod's `House` ran."""
    holder: Any = pod
    return holder.tools.ran
