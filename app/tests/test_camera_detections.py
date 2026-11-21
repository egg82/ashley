"""A camera's own detector event as a sense, and its first use: the doorbell ringing puts that camera's feed on the visible
screens. A stand-in Home Assistant tells an event entity's state change over the held socket (the state is when its last
event came, the attribute `event_type` which); the real held-states socket, the Home Assistant camera adapter, the camera
router, the detections record in Postgres and the open-screens record do the rest. A class not in `show_feed_on`, an event
inside the camera's gap, a camera off the household's list, an event told twice and one heard by both sites' pods each put
nothing more on the screens, and no log names a camera or an entity."""

import asyncio
import logging
import os
from collections import Counter
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from ashley import services
from ashley.cameras.cameras import Cameras
from ashley.cameras.detection_settings import DetectionSettings
from ashley.cameras.detections import Detections
from ashley.cameras.detections_postgres import PostgresDetections
from ashley.cameras.model import Detection
from ashley.cameras.routed import RoutedCameras
from ashley.channels.devices import Devices
from ashley.channels.kiosk import detected
from ashley.channels.model import Device, Listed
from ashley.connections.connections import Connections
from ashley.connections.postgres import PostgresConnections
from ashley.connections.sealing import Sealer
from ashley.connections.settings_read import SettingsReader
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.cameras import NAME, HaCameras
from ashley.home_assistant.ha_held import SocketStates
from ashley.home_assistant.held_states import HeldStates
from ashley.home_assistant.homes import Home, Homes
from ashley.home_assistant.kind import HOME_ASSISTANT
from ashley.home_assistant.house_settings import load as load_house
from ashley.live.events import FeedChanged, Shown
from ashley.live.live import Live
from ashley.live.postgres_screens import PostgresScreens
from ashley.live.screens import Screens
from ashley.logs import Logfmt
from ashley.senses.presence import Presence
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person
from files_support import sync
from ha_held_support import SETTINGS, Clock, FakeHa, FakeHomes, Naps, home_of
from house_devices_support import HouseDevices
from house_double_support import MemoryHouse, state
from live_support import FakeLive
from money_support import HeldConnections
from respond_support import FakePresence
from screen_bench_support import device as make_device
from test_camera_port import HALL, PORCH, Settings

BELL, MOTION, HALL_BELL = "event.zq_porch_doorbell", "event.zq_porch_motion", "event.zq_hall_doorbell"
SEEN = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
SETTINGS_ = DetectionSettings(frozenset({"ring"}), 30, 86400, 60)


@dataclass
class World:
    home: int
    kiosk: int
    ha: FakeHa
    live: FakeLive
    screens: Screens
    database: PoolDatabase
    token: str
    settings: Settings
    clock: list[datetime]
    watching: set[int]

    async def tick(self) -> Counter[str]:
        return await detected.tick(SETTINGS_, self.watching, lambda: self.clock[0])

    async def ring(self, entity: str, at: datetime, kind: str = "ring") -> None:
        self.clock[0] = at
        self.ha.attributes[entity] = {"event_type": kind}
        await self.ha.change(entity, at.isoformat())

    async def shown(self) -> str | None:
        found = await self.screens.feed_of(self.token, self.clock[0], device_id=self.kiosk)
        return None if found is None else found.camera_id


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    home = household(url)
    ann = person(url, home, "Ann")
    kiosk = make_device(url, home)
    database = PoolDatabase(url)
    await database.open()
    ha = FakeHa({BELL: "unknown", MOTION: "unknown", HALL_BELL: "unknown"})
    house = MemoryHouse()
    house.things = [state(PORCH, "Porch", "idle"), state(HALL, "Hall", "idle")]
    house.detector_of = {BELL: PORCH, MOTION: PORCH, HALL_BELL: HALL}
    held = HeldConnections()
    held.connect(home, "http://ha.test", "k", NAME)
    screens, live, settings = PostgresScreens(database), FakeLive(), Settings((PORCH, HALL))
    states = SocketStates(SETTINGS, load_house(), Naps(), Clock())
    async with home_of(ha) as bare:
        homes = FakeHomes(Home(home, bare.home_assistant, house), household=home)
        holding = asyncio.create_task(states.hold(lambda: None))
        await asyncio.sleep(0)
        for interface, service in ((Connections, held), (Homes, homes), (HeldStates, states),
                                   (Cameras, RoutedCameras({NAME: HaCameras()}, 3)), (SettingsReader, settings),
                                   (Screens, screens), (Live, live), (Presence, FakePresence(frozenset({ann}))),
                                   (Detections, PostgresDetections(database)),
                                   (Devices, HouseDevices({home: [Listed(Device(kiosk, home, "tablet", "hallway", "present",
                                                                                "text", "chat"), "other")]}))):
            services.register(interface, service)
        token = str(uuid4())
        await screens.device_opened(home, kiosk, token)
        await screens.device_visible(kiosk, token, True)
        try:
            yield World(home, kiosk, ha, live, screens, database, token, settings, [SEEN], set())
        finally:
            holding.cancel()
            await asyncio.gather(holding, return_exceptions=True)
            for interface in (Connections, Homes, HeldStates, Cameras, SettingsReader, Screens, Live, Presence, Detections,
                              Devices):
                services.unregister(interface)
            await database.close()


def outcomes(caplog: pytest.LogCaptureFixture) -> list[str]:
    found = [Logfmt().format(r) for r in caplog.records if "event=camera.detection " in Logfmt().format(r)]
    return [line.split("outcome=")[1].split()[0] for line in found]


async def settled(caplog: pytest.LogCaptureFixture, count: int) -> list[str]:
    """Wait for `count` detections to have been handled (each logs its outcome)."""
    for _ in range(300):
        if len(outcomes(caplog)) >= count:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.02)
    return outcomes(caplog)


@sync
async def test_a_ring_puts_the_doorbell_cameras_feed_on_the_visible_screen(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        counts = await w.tick()
        assert (counts["households"], counts["followed"]) == (1, 3)
        assert w.ha.subscribed() == sorted([BELL, MOTION, HALL_BELL])
        await w.ring(BELL, SEEN)
        assert await settled(caplog, 1) == ["shown"]
        assert await w.shown() == PORCH and w.live.published == [FeedChanged(Shown(w.home, None))]


@sync
async def test_a_class_not_in_the_config_puts_nothing_on_the_screens(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        await w.tick()
        await w.ring(MOTION, SEEN, "camera_person")
        assert await settled(caplog, 1) == ["ignored"]
        assert await w.shown() is None and w.live.published == []


@sync
async def test_a_second_ring_inside_the_cameras_gap_does_nothing_and_one_after_it_shows_again(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        await w.tick()
        await w.ring(BELL, SEEN)
        await w.ring(BELL, SEEN + timedelta(seconds=SETTINGS_.min_gap_s - 20))
        assert await settled(caplog, 2) == ["shown", "too_soon"]
        assert len(w.live.published) == 1
        await w.ring(BELL, SEEN + timedelta(seconds=SETTINGS_.min_gap_s + 1))
        assert await settled(caplog, 3) == ["shown", "too_soon", "shown"] and len(w.live.published) == 2


@sync
async def test_a_camera_off_the_households_list_is_not_followed_until_it_is_named(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        w.settings.looks = (PORCH,)
        await w.tick()
        assert w.ha.subscribed() == sorted([BELL, MOTION])
        await w.ring(HALL_BELL, SEEN)
        await asyncio.sleep(0.05)
        assert outcomes(caplog) == [] and await w.shown() is None
        w.settings.looks = (HALL,)
        await w.tick()
        assert w.ha.subscribed() == [HALL_BELL]
        await w.ring(HALL_BELL, SEEN + timedelta(seconds=1))
        assert await settled(caplog, 1) == ["shown"] and await w.shown() == HALL


@sync
async def test_switching_the_camera_port_off_lets_go_of_the_detectors(db_url: str) -> None:
    async with world(db_url) as w:
        await w.tick()
        assert len(w.ha.subscribed()) == 3
        w.settings.off = frozenset({"camera"})
        counts = await w.tick()
        assert w.ha.subscribed() == [] and counts["followed"] == 0 and w.watching == {w.home}


@sync
async def test_the_same_event_told_twice_or_heard_by_both_sites_acts_once(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        await w.tick()
        await w.ring(BELL, SEEN)
        await w.ring(BELL, SEEN)
        assert await settled(caplog, 2) == ["shown", "duplicate"]
        other_site = PostgresDetections(w.database)
        services.register(Detections, other_site)
        assert await detected.act(w.home, Detection(PORCH, "ring", SEEN), SETTINGS_, SEEN) == "duplicate"
        assert len(w.live.published) == 1


@sync
async def test_a_change_that_names_no_class_or_no_time_is_no_detection(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        await w.tick()
        await w.ha.change(BELL, "unavailable")
        w.ha.attributes[BELL] = {}
        await w.ha.change(BELL, SEEN.isoformat())
        await asyncio.sleep(0.05)
        assert outcomes(caplog) == [] and await w.shown() is None


@sync
async def test_nobody_looking_shows_nothing_and_does_not_use_up_the_gap(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        await w.tick()
        await w.screens.device_visible(w.kiosk, w.token, False)
        await w.ring(BELL, SEEN)
        assert await settled(caplog, 1) == ["no_screen"]
        await w.screens.device_visible(w.kiosk, w.token, True)
        await w.ring(BELL, SEEN + timedelta(seconds=1))
        assert await settled(caplog, 2) == ["no_screen", "shown"]


@sync
async def test_no_log_names_a_camera_or_an_entity(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with world(db_url) as w:
        await w.tick()
        await w.ring(BELL, SEEN)
        await settled(caplog, 1)
        w.settings.off = frozenset({"camera"})
        await w.tick()
    text = "\n".join(Logfmt().format(r) for r in caplog.records)
    assert "camera.detection" in text and "zq_" not in text


@sync
async def test_detections_are_claimed_once_by_camera_and_time_and_a_shown_one_holds_the_gap(db_url: str) -> None:
    home = household(db_url)
    database = PoolDatabase(db_url)
    await database.open()
    try:
        store = PostgresDetections(database)
        ring = Detection(PORCH, "ring", SEEN)
        assert await store.claim(home, ring, 30) == "new" and await store.claim(home, ring, 30) == "duplicate"
        await store.shown(home, ring)
        soon = Detection(PORCH, "ring", SEEN + timedelta(seconds=29))
        assert await store.claim(home, soon, 30) == "too_soon"
        assert await store.claim(home, Detection(PORCH, "ring", SEEN + timedelta(seconds=31)), 30) == "new"
        assert await store.claim(home, Detection(HALL, "ring", SEEN), 30) == "new"
        assert await store.prune(SEEN + timedelta(days=2), 86400) == 4
        assert await store.claim(home, ring, 30) == "new"
    finally:
        await database.close()


@sync
async def test_the_households_holding_a_connection_of_a_kind_are_listed(db_url: str) -> None:
    database = PoolDatabase(db_url)
    await database.open()
    try:
        connections = PostgresConnections(database, Sealer({1: os.urandom(32)}, current=1))
        first, second = household(db_url, "one"), household(db_url, "two")
        for home, kind in ((second, HOME_ASSISTANT.name), (first, HOME_ASSISTANT.name), (household(db_url, "three"), "sure")):
            await connections.add(home, kind, "main", "http://x.test", "k", person(db_url, home))
        assert await connections.households_of_kinds([HOME_ASSISTANT.name]) == (first, second)
        assert await connections.households_of_kinds([]) == ()
    finally:
        await database.close()
