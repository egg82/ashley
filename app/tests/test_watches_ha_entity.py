"""The `ha_entity` kind through the watches job over a real database and a stand-in Home Assistant (`ha_held_support`):
she arms a watch on a thing the way she arms any kind, the job holds the subscription, and a state change the house
tells nudges a check that wakes her at once; a dropped socket is subscribed again and the change made while it was down
wakes her; a thing the house does not have is refused at arming; and what each read maps to."""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.ha_held import SocketStates
from ashley.home_assistant.held_states import EntityState, HeldStates
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import HouseUnavailable
from ashley.home_assistant.house_settings import load as load_house
from ashley.watches import job
from ashley.watches.arming import Ask, Seen, look, start
from ashley.watches.config import CONFIG
from ashley.watches.ha_entity import NAME, HaEntity, items_of
from ashley.watches.model import Check, Quiet, ReadFailed, Woke
from ashley.watches.postgres import PostgresWatches
from ashley.watches.registry import KINDS
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, scalar
from ha_held_support import SETTINGS, Clock, FakeHa, FakeHomes, Naps, home_of, until
from watch_job_support import watch

DOOR = "binary_sensor.back_door"


class Recording(PostgresWatches):
    """The real store, noting each check it recorded: `stored` is set at each one, and `parked` (set by the job's pause)
    is cleared at each, so it is set again only once the job has finished the round that recorded it."""

    recorded: list[Check]
    stored: asyncio.Event
    parked: asyncio.Event

    async def record(self, watch_id: int, version: int, check: Check) -> bool:
        stored = await super().record(watch_id, version, check)
        if stored:
            self.recorded.append(check)
            self.parked.clear()
            self.stored.set()
        return stored


@dataclass
class World:
    ha: FakeHa
    store: Recording
    db: PoolDatabase
    naps: Naps
    ticks: asyncio.Event
    home: int
    who: int

    async def due_now(self) -> None:
        async with self.db.connection() as conn:
            await conn.execute("UPDATE watches SET next_check_at = now() - interval '1 second'")

    async def tick(self) -> None:
        """Let the job's pause end once, as `tick_s` passing does."""
        self.ticks.set()

    async def recorded(self, kind: type, n: int = 1) -> None:
        """Wait until the store has recorded `n` checks of `kind`."""
        while sum(isinstance(c, kind) for c in self.store.recorded) < n:
            self.store.stored.clear()
            await self.store.stored.wait()

    async def parked(self) -> None:
        """Wait until the job is paused with nothing left to do since the last check it recorded."""
        await self.store.parked.wait()


@asynccontextmanager
async def world(url: str, ha: FakeHa) -> AsyncGenerator[World]:
    home = household(url)
    who = person(url, home)
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    store = Recording(db)
    store.recorded, store.stored, store.parked = [], asyncio.Event(), asyncio.Event()
    naps, ticks = Naps(), asyncio.Event()

    async def pause(_: float) -> None:
        store.parked.set()
        await ticks.wait()
        ticks.clear()

    async with home_of(ha) as connected:
        wired = ((Watches, store), (Homes, FakeHomes(connected, home)),
                 (HeldStates, SocketStates(SETTINGS, load_house(), naps, Clock())))
        for interface, impl in wired:
            services.register(interface, impl)
        running = asyncio.create_task(job.run(CONFIG, KINDS, pause))
        try:
            yield World(ha, store, db, naps, ticks, home, who)
        finally:
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            for interface, _ in wired:
                services.unregister(interface)
            await db.close()


async def arm(w: World, target: str = DOOR) -> Seen | ReadFailed | None:
    now = datetime.now(UTC)
    seen = await look(w.home, w.who, NAME, target, now)
    if isinstance(seen, Seen):
        await start(Ask(w.home, w.who, None, NAME, target, None, None, None), seen, now)
    return seen


def wakes(url: str) -> list[str]:
    rows = scalar(url, "SELECT coalesce(json_agg(changes ORDER BY id), '[]') FROM wakes WHERE kind = 'watch'")
    return [i["after"]["state"] for c in rows for i in c["items"]]


def run(scenario: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(scenario, 10))


def test_a_change_the_house_tells_wakes_her_at_once_through_the_subscription(db_url: str) -> None:
    ha = FakeHa({DOOR: "off"}, {DOOR: "Back door"})

    async def go() -> None:
        async with world(db_url, ha) as w:
            seen = await arm(w)
            assert seen == Seen("Back door", {DOOR: {"state": "off"}})
            await w.due_now()
            await w.tick()
            await w.recorded(Quiet)
            assert ha.subscribed() == [DOOR]
            await w.parked()
            await w.due_now()
            await ha.change(DOOR, "on")
            await w.recorded(Woke)
        assert wakes(db_url) == ["on"]
        assert scalar(db_url, "SELECT label FROM watches") == "Back door"
    run(go())


def test_a_dropped_socket_is_subscribed_again_and_the_change_made_meanwhile_wakes_her(db_url: str) -> None:
    ha = FakeHa({DOOR: "off"})

    async def go() -> None:
        async with world(db_url, ha) as w:
            await arm(w)
            await w.due_now()
            await w.tick()
            await w.recorded(Quiet)
            await ha.drop()
            await until(lambda: w.naps.taken, "a backoff")
            ha.states[DOOR] = "on"
            w.naps.free = 1
            await until(lambda: ha.connections == 2 and ha.subscribed() == [DOOR], "the door subscribed again")
            await w.due_now()
            await w.tick()
            await w.recorded(Woke)
        assert wakes(db_url) == ["on"]
    run(go())


def test_a_thing_the_house_does_not_have_is_refused_at_arming(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, FakeHa({DOOR: "off"})) as w:
            assert await arm(w, "sensor.not_there") is None
            assert await arm(w, "not an entity id") is None
        assert scalar(db_url, "SELECT count(*) FROM watches") == 0
    run(go())


class Answers(HeldStates):
    def __init__(self, found: dict[str, EntityState | None] | None, fail: Exception | None = None) -> None:
        self.found, self.fail = found, fail

    async def hold(self, changed: Callable[[], None]) -> None:
        return None

    async def states(self, household_id: int, entity_ids: Sequence[str]) -> dict[str, EntityState | None] | None:
        if self.fail is not None:
            raise self.fail
        return self.found


@pytest.mark.parametrize("answers,expected", [
    (Answers({DOOR: EntityState("on", "Back door")}), {DOOR: {"state": "on"}}),
    (Answers({DOOR: None}), {}),
    (Answers(None), ReadFailed("not_connected")),
])
def test_each_answer_maps_to_a_read(answers: Answers, expected: object) -> None:
    services.register(HeldStates, answers)
    try:
        got = asyncio.run(HaEntity().read([watch(1, kind=NAME, target=DOOR)]))
    finally:
        services.unregister(HeldStates)
    assert got == {1: expected}


def test_an_unreachable_house_fails_every_watch_unreachable() -> None:
    services.register(HeldStates, Answers(None, HouseUnavailable("websocket: refused")))
    try:
        got = asyncio.run(HaEntity().read([watch(1, kind=NAME, target=DOOR), watch(2, kind=NAME, target="light.x")]))
    finally:
        services.unregister(HeldStates)
    assert got == {1: ReadFailed("unreachable"), 2: ReadFailed("unreachable")}


def test_items_track_the_state_alone() -> None:
    assert items_of(DOOR, EntityState("on", "Back door")) == {DOOR: {"state": "on"}}
    assert CONFIG.kinds[NAME].track == ("state",) and not CONFIG.kinds[NAME].outside
    assert json.dumps(items_of(DOOR, None)) == "{}"
