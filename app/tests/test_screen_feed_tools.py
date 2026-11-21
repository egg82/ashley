"""Her `screen_show_camera` and `screen_clear_camera` over the camera port and the open-screens record in Postgres: a camera
she may look through goes on the screens `ashley.channels.kiosk.announce.chosen` picks (the kiosk when someone is home, the
foregrounded page of someone away), is announced on Live as a change and read back by the screen's own token; a camera that is
not on the household's list or has no live video is refused and nothing is shown; nobody looking announces nothing; the
feed leaves by itself once the seconds held in `live.json` are up, by a clock the test moves; what a screen shows is
the record's, so another instance of the tool clears it; and no log names a camera."""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from ashley import services
from ashley.cameras.cameras import Cameras
from ashley.cameras.model import LiveConfig
from ashley.cameras.routed import RoutedCameras
from ashley.channels.devices import Devices
from ashley.channels.model import Device, Listed
from ashley.channels.screen_feed_tools import ScreenFeedTools
from ashley.connections.connections import Connections
from ashley.connections.settings_read import SettingsReader
from ashley.db.pool import PoolDatabase
from ashley.home_assistant.cameras import NAME, HaCameras
from ashley.home_assistant.homes import Homes
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.events import FeedChanged, Shown
from ashley.live.live import Live, load as live_config
from ashley.live.postgres_screens import PostgresScreens
from ashley.live.screens import Screens
from ashley.senses.presence import Presence
from ashley.tools import screen_feed_specs
from contract.conversations_support import db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person
from files_support import sync
from homes_support import AnyHousehold
from house_devices_support import HouseDevices
from house_double_support import MemoryHouse, state
from live_support import FakeLive
from money_support import HeldConnections
from respond_support import FakePresence
from screen_bench_support import device as make_device
from test_camera_port import BACK, HALL, PORCH, Settings

FEED_S = live_config().feed_s
START = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@dataclass
class World:
    home: int
    ann: int
    bea: int
    kiosk: int
    house: MemoryHouse
    live: FakeLive
    presence: FakePresence
    screens: Screens
    tokens: dict[str, str]


async def _open(screens: Screens, home: int, ann: int, bea: int, kiosk: int) -> dict[str, str]:
    tokens = {"ann": str(uuid4()), "bea": str(uuid4()), "kiosk": str(uuid4())}
    await screens.opened(home, ann, tokens["ann"])
    await screens.opened(home, bea, tokens["bea"])
    await screens.device_opened(home, kiosk, tokens["kiosk"])
    for who, token in ((ann, tokens["ann"]), (bea, tokens["bea"])):
        await screens.person_visible(who, token, True)
    await screens.device_visible(kiosk, tokens["kiosk"], True)
    return tokens


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    home = household(url)
    ann, bea = person(url, home, "Ann"), person(url, home, "Bea")
    kiosk = make_device(url, home)
    database = PoolDatabase(url)
    await database.open()
    house = MemoryHouse()
    house.things = [state(PORCH, "Porch", "idle"), state(HALL, "Hall", "idle"), state(BACK, "Back garden", "idle")]
    house.live_cfg = LiveConfig((), None)
    held = HeldConnections()
    held.connect(home, "http://ha.test", "k", NAME)
    screens = PostgresScreens(database)
    made = World(home, ann, bea, kiosk, house, FakeLive(), FakePresence(frozenset({ann})), screens, {})
    for interface, service in ((Connections, held), (Homes, AnyHousehold(house)), (Cameras, RoutedCameras({NAME: HaCameras()}, 3)),
                               (SettingsReader, Settings()), (Screens, screens), (Live, made.live),
                               (Presence, made.presence),
                               (Devices, HouseDevices({home: [Listed(Device(kiosk, home, "tablet", "hallway", "present",
                                                                            "text", "chat"), "other")]}))):
        services.register(interface, service)
    made.tokens = await _open(screens, home, ann, bea, kiosk)
    try:
        yield made
    finally:
        for interface in (Connections, Homes, Cameras, SettingsReader, Screens, Live, Presence, Devices):
            services.unregister(interface)
        await database.close()


def tools(w: World, now: datetime = START, person_id: int | None = None, device: int | None = None) -> ScreenFeedTools:
    return ScreenFeedTools(w.home, w.ann if person_id is None and device is None else person_id, device, lambda: now)


async def call(t: ScreenFeedTools, name: str, **arguments: object) -> ToolResult:
    return await t.call(ToolCall("c1", name, arguments))


def screens_of(result: ToolResult) -> int:
    assert not result.is_error, result.content
    body: dict[str, int] = json.loads(result.content)
    return body["screens"]


async def shown_on(w: World, now: datetime) -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for name, who in (("ann", {"person_id": w.ann}), ("bea", {"person_id": w.bea}), ("kiosk", {"device_id": w.kiosk})):
        feed = await w.screens.feed_of(w.tokens[name], now, **who)
        found[name] = None if feed is None else feed.camera_id
    return found


@sync
async def test_a_camera_goes_on_the_kiosk_when_someone_is_home_and_on_the_page_of_someone_away(db_url: str) -> None:
    async with world(db_url) as w:
        assert screens_of(await call(tools(w), screen_feed_specs.SHOW, camera=PORCH)) == 2
        assert await shown_on(w, START) == {"ann": None, "bea": PORCH, "kiosk": PORCH}
        assert w.live.published == [FeedChanged(Shown(w.home, None))]
        assert w.house.reads > 0 and w.house.offers == []   # her side only ever signals: no offer comes from a tool


@sync
async def test_a_camera_off_the_list_or_without_live_video_is_refused_and_nothing_is_shown(db_url: str) -> None:
    async with world(db_url) as w:
        refused = await call(tools(w), screen_feed_specs.SHOW, camera=BACK)
        assert refused.is_error and refused.content.startswith("no_such_camera")
        w.house.no_live = frozenset({HALL})
        plain = await call(tools(w), screen_feed_specs.SHOW, camera=HALL)
        assert plain.is_error and plain.content.startswith("no_live_feed")
        assert await shown_on(w, START) == {"ann": None, "bea": None, "kiosk": None} and w.live.published == []


@sync
@pytest.mark.parametrize("arguments", [{}, {"camera": ""}, {"camera": 4}, {"camera": PORCH, "device_id": 1}])
async def test_bad_arguments_show_nothing(db_url: str, arguments: dict[str, object]) -> None:
    async with world(db_url) as w:
        assert (await call(tools(w), screen_feed_specs.SHOW, **arguments)).content.startswith("bad_arguments")
        assert await shown_on(w, START) == {"ann": None, "bea": None, "kiosk": None}


@sync
async def test_nobody_looking_shows_nothing_and_announces_nothing(db_url: str) -> None:
    async with world(db_url) as w:
        for name, who in (("ann", w.ann), ("bea", w.bea)):
            await w.screens.person_visible(who, w.tokens[name], False)
        await w.screens.device_visible(w.kiosk, w.tokens["kiosk"], False)
        assert screens_of(await call(tools(w), screen_feed_specs.SHOW, camera=PORCH)) == 0
        assert w.live.published == []


@sync
async def test_the_feed_leaves_by_itself_when_the_seconds_held_in_data_are_up(db_url: str) -> None:
    async with world(db_url) as w:
        await call(tools(w), screen_feed_specs.SHOW, camera=PORCH)
        assert (await shown_on(w, START + timedelta(seconds=FEED_S - 1)))["kiosk"] == PORCH
        assert (await shown_on(w, START + timedelta(seconds=FEED_S)))["kiosk"] is None
        feed = await w.screens.feed_of(w.tokens["kiosk"], START, device_id=w.kiosk)
        assert feed is not None and feed.until == START + timedelta(seconds=FEED_S)


@sync
async def test_what_a_screen_shows_is_the_records_so_another_instance_clears_it(db_url: str) -> None:
    async with world(db_url) as w:
        await call(tools(w), screen_feed_specs.SHOW, camera=PORCH)
        w.live.published.clear()
        assert screens_of(await call(tools(w), screen_feed_specs.CLEAR)) == 2
        assert await shown_on(w, START) == {"ann": None, "bea": None, "kiosk": None}
        assert w.live.published == [FeedChanged(Shown(w.home, None))]
        assert screens_of(await call(tools(w), screen_feed_specs.CLEAR)) == 0
        assert len(w.live.published) == 1


@sync
async def test_a_turn_on_the_kiosks_own_thread_reaches_that_screen_only(db_url: str) -> None:
    async with world(db_url) as w:
        w.presence.answer = frozenset[int]()   # everyone known is away, so pages show it and the kiosk would not
        assert screens_of(await call(tools(w, device=w.kiosk, person_id=None), screen_feed_specs.SHOW, camera=PORCH)) == 2
        w.presence.answer = frozenset({w.ann, w.bea})
        await call(tools(w), screen_feed_specs.CLEAR)
        assert screens_of(await call(tools(w, device=w.kiosk, person_id=None), screen_feed_specs.SHOW, camera=PORCH)) == 1
        assert await shown_on(w, START) == {"ann": None, "bea": None, "kiosk": PORCH}


@sync
async def test_the_tools_are_offered_only_with_a_screen_in_reach_and_a_camera_source(db_url: str) -> None:
    async with world(db_url) as w:
        assert [s.name for s in (await tools(w).catalogue()).specs] == [screen_feed_specs.SHOW, screen_feed_specs.CLEAR]
        assert (await ScreenFeedTools(w.home, None, None).catalogue()).specs == ()
        assert (await ScreenFeedTools(w.home, None, w.kiosk + 1).catalogue()).specs == ()
        services.register(Devices, HouseDevices({w.home: []}))
        assert (await tools(w).catalogue()).specs == ()
        services.register(SettingsReader, Settings(off=frozenset({"camera"})))
        services.register(Devices, HouseDevices({w.home: [Listed(Device(w.kiosk, w.home, "t", "h", "present", "text", "chat"),
                                                                 "other")]}))
        assert (await tools(w).catalogue()).specs == ()


@sync
async def test_both_tools_change_what_people_see_and_are_judged_like_the_screen_tools() -> None:
    assert [(s.name, s.reads, s.outside, s.tier) for s in screen_feed_specs.specs()] == [
        (screen_feed_specs.SHOW, False, False, "judged"), (screen_feed_specs.CLEAR, False, False, "judged")]


@sync
async def test_the_screens_or_the_cameras_failing_is_an_error_result(db_url: str) -> None:
    async with world(db_url) as w:
        w.house.down = True
        down = await call(tools(w), screen_feed_specs.SHOW, camera=PORCH)
        assert down.is_error and down.content.startswith("unavailable")
        w.house.down = False
        services.unregister(Screens)
        assert (await call(tools(w), screen_feed_specs.CLEAR)).content.startswith("unavailable")
        assert (await call(tools(w), "screen_nope")).content.startswith("unknown_tool")


@sync
async def test_the_log_names_ids_and_counts_never_a_camera(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async with world(db_url) as w:
        with caplog.at_level(logging.DEBUG):
            await call(tools(w), screen_feed_specs.SHOW, camera=PORCH)
            await call(tools(w), screen_feed_specs.SHOW, camera=BACK)
            await call(tools(w), screen_feed_specs.CLEAR)
        assert "tools.call" in caplog.text
        assert "Porch" not in caplog.text and "zq_porch" not in caplog.text and "zq_back" not in caplog.text
