"""Her bench tools on a real Postgres Workshop: a recording Live, tool-call builders, and readers for JSON results by
field name wherever the field sits."""

import json
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import count
from typing import Any

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command
from ashley.workshop.model import By, Owner, Size, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from live_support import FakeLive
from shelf_service_support import World, world

_ids = count(1)


@dataclass
class Env:
    world: World
    workshop: Workshop
    live: FakeLive


@asynccontextmanager
async def env(url: str) -> AsyncGenerator[Env]:
    db = PoolDatabase(url)
    await db.open()
    live = FakeLive()
    shipped = PostgresWorkshop(db, workshop_rules.load())
    services.register(Live, live)
    services.register(Workshop, shipped)
    try:
        yield Env(world(url), shipped, live)
    finally:
        for interface in (Live, Workshop):
            services.unregister(interface)
        await db.close()


def tools(e: Env, bench_id: int, who: str = "alana") -> BenchTools:
    owner: Owner = getattr(e.world, who)
    return BenchTools(owner.household_id, owner.person_id, bench_id)


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(f"call-{next(_ids)}", name, arguments)


async def opened(e: Env, owner: Owner, title: str = "bench") -> int:
    return (await e.workshop.open(owner, title)).id


async def put(e: Env, owner: Owner, bench_id: int, command: Command) -> int | None:
    return (await e.workshop.apply(owner, bench_id, command)).piece_id


def person_add(owner: Owner, title: str = "t", body: str = "b", kind: str = "note", size: Size = "medium") -> Add:
    return Add(By(owner.person_id), kind, Text(title, body), size)


def js(result: ToolResult) -> Any:
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


def values_of(result: ToolResult, key: str) -> list[object]:
    return [d[key] for d in dicts(js(result)) if key in d]


def pieces_with_title(result: ToolResult) -> list[dict[str, object]]:
    """The objects of a result that look like pieces (an `id` and a `title`), in the order they appear."""
    return [d for d in dicts(js(result)) if "id" in d and "title" in d]
