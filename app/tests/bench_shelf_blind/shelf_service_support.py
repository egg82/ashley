"""The Postgres `Workshop` through its abstract interface: two households with three people, a recording Live, and
helpers that apply commands as the owner."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.events import BenchChanged
from ashley.live.live import Live
from ashley.workshop.commands import Command
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Applied, Workshop
from contract.conversations_support import household, person
from live_support import FakeLive
from shelf_support import RULES, add


@dataclass(frozen=True)
class World:
    """Alana and Sam share household 1; Zed is alone in household 2."""

    url: str
    alana: Owner
    sam: Owner
    zed: Owner


def world(url: str) -> World:
    h1, h2 = household(url, "one"), household(url, "two")
    return World(url, Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


@asynccontextmanager
async def workshop(url: str, live: FakeLive | None = None) -> AsyncGenerator[Workshop]:
    db = PoolDatabase(url)
    await db.open()
    services.register(Live, live if live is not None else FakeLive())
    try:
        yield PostgresWorkshop(db, RULES)
    finally:
        await db.close()


def by(owner: Owner) -> By:
    return By(owner.person_id)


async def do(s: Workshop, owner: Owner, bench_id: int, *commands: Command) -> list[Applied]:
    """Each command applied as `owner` (its `by` replaced), in turn."""
    return [await s.apply(owner, bench_id, replace(c, by=by(owner))) for c in commands]


def changed(live: FakeLive) -> list[BenchChanged]:
    return [e for e in live.published if isinstance(e, BenchChanged)]


async def bench_of(s: Workshop, owner: Owner, *commands: Command, title: str = "t") -> int:
    bench = await s.open(owner, title)
    await do(s, owner, bench.id, *commands)
    return bench.id


A3 = [add("a", "A", size="small"), add("b", "B", size="medium"), add("c", "C", size="large")]
