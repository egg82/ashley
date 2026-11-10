"""Shared pieces of the bench-quiet blind contract tests: builders for an Inbound and a Reply, readers for what a
step was asked, a real-Postgres world for the hearing cases and for a lead bench's tools, and logfmt events."""

import itertools
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from ashley import services
from ashley.logs import Logfmt
from ashley.channels.model import Inbound
from ashley.conversations.conversations import Conversations
from ashley.conversations.model import Kind
from ashley.conversations.policy import load as load_policy
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.inference.model import Message, Prompt, ToolCall, ToolResult, ToolResults
from ashley.inference.reply import Reply
from ashley.live.live import Live
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.tools.tools import Catalogue, Tools
from ashley.inference.model import ToolSpec
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import events, household, person
from live_support import FakeLive
from respond_support import Fakes

PUBLIC = "https://ashley.test"
SECRET = "violet-armadillo-4471"  # gitleaks:allow (test fixture)


def inbound(kind: Kind = "brainstorm", text: str = "tighten the plan", speaker_id: int | None = 1,
            household_id: int = 10, thread: str = "bench:1") -> Inbound:
    return Inbound(household_id, thread, text, kind, "text", "owner", speaker_id, False, None, "web")


def reply(chars: int, spoken: str = "ok") -> Reply:
    return Reply(spoken=spoken, text="x" * chars)


def messages_of(prompt: Prompt) -> list[Message]:
    return [m for m in prompt.messages if isinstance(m, Message)]


def read_by_her(prompt: Prompt) -> str:
    """Everything the model was shown as the exchange: messages and tool results, never the system prompt."""
    parts = [m.text for m in messages_of(prompt)]
    parts += [r.content for e in prompt.messages if isinstance(e, ToolResults) for r in e.results]
    return "\n".join(parts)


def logged(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, str]]:
    return events(caplog.text, event)


def capture(caplog: pytest.LogCaptureFixture) -> None:
    """Records every level and renders each as the app's own logfmt line, so `logged` reads the fields."""
    caplog.set_level(logging.DEBUG)
    caplog.handler.setFormatter(Logfmt())


def steps(wired: Fakes) -> int:
    return len(wired.inference.prompts)


@dataclass(frozen=True)
class World:
    """Alana and Sam share household `home`; Zed is alone in `next_door`."""

    url: str
    home: int
    alana: int
    sam: int
    next_door: int
    zed: int


class Households(People):
    def __init__(self, world: World) -> None:
        w = world
        self._homes = {
            w.home: (Person(w.alana, w.home, "Alana"), Person(w.sam, w.home, "Sam")),
            w.next_door: (Person(w.zed, w.next_door, "Zed"),)}

    async def household(self, household_id: int) -> Household | None:
        people = self._homes.get(household_id)
        return None if people is None else Household(household_id, "h", "UTC", "", people)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


def world_on(url: str) -> World:
    home, away = household(url, "home"), household(url, "next door")
    return World(url, home, person(url, home, "Alana"), person(url, home, "Sam"), away, person(url, away, "Zed"))


@dataclass
class Real:
    world: World
    conversations: Conversations
    workshop: Workshop
    live: FakeLive


class Shared(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("weather", "d", {"type": "object", "properties": {}, "required": []}),), "G")

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "sunny")


@asynccontextmanager
async def real(url: str, fakes: Fakes | None = None) -> AsyncGenerator[Real]:
    """Postgres Conversations and Workshop on a migrated database, people read from that database, registered in the
    locator; with `fakes` its inference stays the model the test scripts."""
    db = PoolDatabase(url)
    await db.open()
    world = world_on(url)
    live = FakeLive()
    conversations = PostgresConversations(db, load_policy())
    workshop = PostgresWorkshop(db, workshop_rules.load())
    services.register(Live, live)
    services.register(Workshop, workshop)
    services.register(People, Households(world))
    services.register(Conversations, conversations)
    if fakes is None:
        services.register(Tools, Shared())
    try:
        yield Real(world, conversations, workshop, live)
    finally:
        for interface in (Live, Workshop, People, Conversations, Tools):
            services.unregister(interface)
        await db.close()


def owner_of(w: World, person_id: int) -> Owner:
    return Owner(w.home, person_id)


_ids = itertools.count(1)


def tc(name: str, **arguments: object) -> ToolCall:
    return ToolCall(f"c{next(_ids)}", name, arguments)


def add_piece(title: str = "t", body: str = "b") -> ToolCall:
    return tc("bench_add", kind="note", title=title, body=body, size="small")


async def piece_count(r: Real, person_id: int, bench_id: int) -> int:
    return len((await r.workshop.read(owner_of(r.world, person_id), bench_id)).pieces)
