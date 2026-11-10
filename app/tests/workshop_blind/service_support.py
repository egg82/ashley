"""The Postgres `Workshop` under test, reached only through its abstract interface: two households with three people,
the service built from its public constructor, a `Live` that checks the command was committed when it is told, and
helpers that read the whole bench and its log back."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.events import BenchChanged, Event
from ashley.live.live import Live
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Rules
from ashley.workshop.workshop import Workshop
from blind_support import RULES
from contract.conversations_support import household, person, scalar
from live_support import FakeLive


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


class CommittedLive(FakeLive):
    """Records each event with how many command rows another connection could see at that moment."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.visible: list[int] = []

    def publish(self, event: Event) -> None:
        super().publish(event)
        self.visible.append(int(scalar(self.url, "SELECT count(*) FROM bench_commands")))


@asynccontextmanager
async def workshop(url: str, rules: Rules = RULES, live: Live | None = None) -> AsyncGenerator[Workshop]:
    """A Postgres workshop on `url` with `live` registered (a recording one by default)."""
    db = PoolDatabase(url)
    await db.open()
    services.register(Live, live if live is not None else FakeLive())
    try:
        yield PostgresWorkshop(db, rules)
    finally:
        await db.close()


def changed(live: FakeLive) -> list[BenchChanged]:
    return [e for e in live.published if isinstance(e, BenchChanged)]


def rows(url: str, table: str) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute(f"SELECT count(*) FROM {table}".encode()).fetchone()
    assert row is not None
    return int(row[0])
