"""Live over LISTEN/NOTIFY against a real Postgres: an event published through one instance (one pod) reaches a screen
subscribed on another, over its own connection; and a listener whose connection is cut (a failover) reconnects and
tells its screens to resync. Each test uses its own channel, so tests never hear each other."""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import psycopg
from ashley.db.database import Database, Probe
from ashley.db.pool import PoolDatabase
from ashley.live import live
from ashley.live.events import HerState, Shown, ThreadTurn, Viewer
from ashley.live.fanout import RESYNC, Subscription
from ashley.live.postgres import PostgresLive
from psycopg import AsyncConnection
from pg import admin_url

ALANA = Viewer(1, 10)
CONFIG = replace(live.load(), reconnect_max_s=0.2)


async def _next(subscription: Subscription) -> object:
    got = await subscription.next(3.0)
    assert got is not None, "nothing arrived"
    return got


async def _listening(url: str, channel: str) -> None:
    """Wait until some connection LISTENs on `channel`, so nothing published before it is lost."""
    for _ in range(300):
        with psycopg.connect(url, autocommit=True) as conn:
            row = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE query = %s",
                               (f'LISTEN "{channel}"',)).fetchone()
        if row is not None and row[0] > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the listener never listened")


def test_an_event_published_on_one_pod_reaches_a_screen_on_another() -> None:
    url, channel = admin_url(), f"live_{uuid.uuid4().hex[:10]}"

    async def scenario() -> list[object]:
        database = PoolDatabase(url)
        await database.open()
        publisher, listener = PostgresLive(url, database, CONFIG, channel), PostgresLive(url, database, CONFIG, channel)
        try:
            async with listener.subscribe(ALANA) as subscription:
                await _listening(url, channel)
                mine = HerState(Shown(1, 10), "t1", "thinking", 180.0)
                publisher.publish(HerState(Shown(1, 11), "t0", "thinking", 180.0))
                publisher.publish(mine)
                publisher.publish(ThreadTurn(Shown(1, 10), "person:10:web"))
                return [await _next(subscription), await _next(subscription)]
        finally:
            await publisher.close()
            await listener.close()
            await database.close()

    got = asyncio.run(asyncio.wait_for(scenario(), 10))
    assert got == [HerState(Shown(1, 10), "t1", "thinking", 180.0), ThreadTurn(Shown(1, 10), "person:10:web")]


def test_a_listener_cut_off_reconnects_and_tells_its_screens_to_resync() -> None:
    url, channel = admin_url(), f"live_{uuid.uuid4().hex[:10]}"

    async def scenario() -> list[object]:
        database = PoolDatabase(url)
        await database.open()
        listener = PostgresLive(url, database, CONFIG, channel)
        try:
            async with listener.subscribe(ALANA) as subscription:
                await _listening(url, channel)
                with psycopg.connect(url, autocommit=True) as conn:
                    conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query = %s",
                                 (f'LISTEN "{channel}"',))
                resync = await _next(subscription)
                await _listening(url, channel)
                listener.publish(HerState(Shown(1, None), "t2", "idle", 180.0))
                return [resync, await _next(subscription)]
        finally:
            await listener.close()
            await database.close()

    assert asyncio.run(asyncio.wait_for(scenario(), 10)) == [RESYNC, HerState(Shown(1, None), "t2", "idle", 180.0)]


class _StuckPublish(Database):
    """A database whose connection is held by a publish until cancelled, and notes that its release ran."""

    def __init__(self) -> None:
        self.held = asyncio.Event()
        self.released = False

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def probe(self) -> Probe:
        return Probe(reachable=True, writable=True)

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[AsyncConnection[tuple[Any, ...]]]:
        self.held.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("the publish was never cancelled")
            yield
        finally:
            self.released = True


def test_close_returns_only_once_a_publish_in_flight_has_let_go_of_its_connection() -> None:
    async def scenario() -> bool:
        database = _StuckPublish()
        live_ = PostgresLive("postgresql://unused", database, CONFIG)
        live_.publish(ThreadTurn(Shown(1, 10), "person:10:web"))
        await database.held.wait()
        await live_.close()
        return database.released

    assert asyncio.run(asyncio.wait_for(scenario(), 10))
