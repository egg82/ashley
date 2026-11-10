"""Shared pieces of the bench-tools blind contract tests: two households with three people, the real Workshop on a
throwaway database registered in the locator with a recording Live, a stand-in for the shared Tools, builders for an
Inbound and a ToolCall, and readers for tool results that look at JSON by field name wherever it sits."""

import json
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from ashley import services
from ashley.channels.model import Inbound, Medium
from ashley.conversations.model import Channel
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.live.live import Live
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Logged, Workshop
from contract.conversations_support import household, person
from live_support import FakeLive

REMINDING = ("remind", "reminders", "cancel_reminder", "change_reminder")
"""The reminder tools a turn with a known speaker is offered where its reply reaches them alone; elsewhere `remind`."""
BENCH_TOOLS = ("bench_read", "bench_read_piece", "bench_add", "bench_edit", "bench_replace", "bench_move", "bench_remove",
               "bench_archive", "bench_shelf", "bench_restore", "bench_undo", "bench_rename", "bench_cue", "bench_point")
_ids = count(1)


@dataclass(frozen=True)
class World:
    """Alana and Sam share household `home`; Zed is alone in `next_door`."""

    url: str
    alana: Owner
    sam: Owner
    zed: Owner


@dataclass
class Env:
    world: World
    workshop: Workshop
    live: FakeLive
    shared: "Shared" = field(default_factory=lambda: Shared())


class Households(People):
    """The world's two households, so a turn's reminder tools can name their people."""

    def __init__(self, world: World) -> None:
        w = world
        home = tuple(Person(o.person_id, o.household_id, n) for o, n in ((w.alana, "Alana"), (w.sam, "Sam")))
        self._homes = {w.alana.household_id: home, w.zed.household_id: (Person(w.zed.person_id, w.zed.household_id,
                                                                              "Zed"),)}

    async def household(self, household_id: int) -> Household | None:
        people = self._homes.get(household_id)
        return None if people is None else Household(household_id, "h", "UTC", "", people)

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


def world_on(url: str) -> World:
    h1, h2 = household(url, "home"), household(url, "next door")
    return World(url, Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


class Shared(Tools):
    """The locator's Tools stand-in: two tools of its own, every call recorded, or unreachable when `down`."""

    def __init__(self, unreachable: tuple[str, ...] = (), down: bool = False) -> None:
        self.calls: list[ToolCall] = []
        self.unreachable = unreachable
        self.down = down

    async def catalogue(self) -> Catalogue:
        if self.down:
            raise ToolsUnavailable("down")
        specs = tuple(ToolSpec(n, "d", {"type": "object", "properties": {}, "required": []})
                      for n in ("lights_on", "weather"))
        return Catalogue(specs, "SHARED-GUIDANCE", self.unreachable)

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        if call.name in ("lights_on", "weather"):
            return ToolResult(call.id, "shared:" + call.name)
        return ToolResult(call.id, "no such tool", is_error=True)


@asynccontextmanager
async def env(url: str) -> AsyncGenerator[Env]:
    """The real Postgres Workshop and a recording Live registered, and a `Shared` as the locator's Tools."""
    db = PoolDatabase(url)
    await db.open()
    live = FakeLive()
    shared = Shared()
    workshop = PostgresWorkshop(db, workshop_rules.load())
    services.register(Live, live)
    services.register(Workshop, workshop)
    services.register(Tools, shared)
    world = world_on(url)
    services.register(People, Households(world))
    try:
        yield Env(world, workshop, live, shared)
    finally:
        for interface in (Live, Workshop, Tools, People):
            services.unregister(interface)
        await db.close()


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(f"call-{next(_ids)}", name, arguments)


def inbound(owner: Owner | None, text: str = "hello", channel: Channel = "web", medium: Medium = "text",
            bench_id: int | None = None, opens_benches: bool = False, device_id: int | None = None,
            later: bool = False) -> Inbound:
    """An Inbound for `owner` (None: no known speaker) with the context fields set."""
    return Inbound(household_id=owner.household_id if owner else 1, thread="t", text=text, kind="chat", medium=medium,
                   audience="owner", speaker_id=owner.person_id if owner else None, shared=False, place=None,
                   channel=channel, later=later, device_id=device_id, bench_id=bench_id, opens_benches=opens_benches)


def person_add(owner: Owner, title: str = "t", body: str = "b", kind: str = "note") -> Add:
    return Add(By(owner.person_id), kind, Text(title, body), "medium")


async def opened(e: Env, owner: Owner, title: str = "bench") -> int:
    return (await e.workshop.open(owner, title)).id


async def put(e: Env, owner: Owner, bench_id: int, command: Command) -> int | None:
    """Apply a person's command; the piece it changed."""
    return (await e.workshop.apply(owner, bench_id, command)).piece_id


def js(result: ToolResult) -> object:
    return json.loads(result.content)


def dicts(node: object) -> Iterator[dict[str, object]]:
    """Every JSON object in a result, however deep."""
    loose: Any = node
    if isinstance(node, dict):
        found = {str(k): v for k, v in dict[object, object](loose).items()}
        yield found
        for v in found.values():
            yield from dicts(v)
    elif isinstance(node, list):
        for v in list[object](loose):
            yield from dicts(v)


def piece_in(result: ToolResult, piece_id: int) -> dict[str, object]:
    """The object in a read result whose `id` is `piece_id` and which carries a title."""
    for d in dicts(js(result)):
        if d.get("id") == piece_id and "title" in d:
            return d
    raise AssertionError(f"no piece {piece_id} in {result.content[:300]}")


def values_of(result: ToolResult, key: str) -> list[object]:
    return [d[key] for d in dicts(js(result)) if key in d]


async def pieces(e: Env, owner: Owner, bench_id: int) -> list[tuple[int, str, str, int, int]]:
    """(id, title, body, version, order) of every piece, read from the Workshop itself."""
    view = await e.workshop.read(owner, bench_id)
    return [(p.id, p.text.title, p.text.body, p.version, p.place.order) for p in view.pieces]


async def log(e: Env, owner: Owner, bench_id: int) -> list[Logged]:
    return await e.workshop.log(owner, bench_id)



