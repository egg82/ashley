"""A reminder said in a room or shown on a screen, over a real database: its turn runs on the device's thread with the
device's audience, place and medium; the satellites singleton says a room's in that room when the satellite is
connected, and a screen's counts as shown when a screen of that device is open on either site; each try is claimed
and recorded on the reminder, so a singleton taking over mid-tries resumes where the last left off and two at once
try once; after `device_tries` tries not reached it is pushed to the phone. Time moves by moving the stored try back
(`device_retry_s`), never by waiting. The device is chosen by its id from the household's own devices, and fits the
route by its form."""

import asyncio
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial

import pytest
from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.model import Device, Listed, Satellite
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as push_config
from ashley.channels.push.subscriptions import Subscription
from ashley.channels.voice import reminders as voice_reminders
from ashley.channels.voice.connection import Announcer
from ashley.channels.wake import reminder_device, runner, screen_delivery
from ashley.channels.wake.config import CONFIG as WAKES
from ashley.inference.model import ToolCall
from ashley.live.screens import Screens
from ashley.senses.wakes import Reminder, Route
from ashley.tools.reminders import ReminderTools
from house_devices_support import HouseDevices
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, run, scalar
from later_support import FakeClips, clips as clips
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions
from screen_bench_support import device
from test_reminder_delivery import age, state
from test_reminder_turn import SAYS, World, world
from voice_support import FakeConnection, FakeTurnLoop, pipeline

PUSH = push_config()
PIPE = pipeline(FakeTurnLoop())


@dataclass
class OpenScreens(Screens):
    """Which devices have a screen open: `shown`."""

    shown: set[int] = field(default_factory=set[int])

    async def opened(self, household_id: int, person_id: int) -> int:
        return 1

    async def device_opened(self, household_id: int, device_id: int) -> int:
        return 1

    async def beat(self, screen_id: int) -> None:
        return None

    async def closed(self, screen_id: int) -> None:
        return None

    async def looking(self, person_id: int, within_s: float) -> bool:
        return False

    async def showing(self, device_id: int, within_s: float) -> bool:
        return device_id in self.shown


@dataclass
class Room:
    """The household's echo (a satellite) and hall screen, by id, and the satellite as the singleton holds it."""

    echo: int
    hall: int
    satellite: Satellite
    screens: OpenScreens


@pytest.fixture
def house() -> Generator[None]:
    yield
    for interface in (Devices, Screens):
        services.unregister(interface)


def furnished(w: World) -> Room:
    echo, hall = device(w.url, w.home, "zq echo"), device(w.url, w.home, "zq hall")
    sat = Device(echo, w.home, "zq echo", "kitchen", "present", "spoken", "command")
    screen = Device(hall, w.home, "zq hall", "hallway", "present", "text", "chat")
    services.register(Devices, HouseDevices({w.home: [Listed(sat, "satellite"), Listed(screen, "other")]}))
    screens = OpenScreens()
    services.register(Screens, screens)
    return Room(echo, hall, Satellite(sat, "zq-echo.invalid", None), screens)


async def fired(w: World, route: Route, device_id: int) -> int:
    wake = await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, "zq brief",
                                           datetime.now(UTC) - timedelta(seconds=1), None, route=route,
                                           device_id=device_id))
    w.model.script = [SAYS]
    await runner.sweep()
    return wake


def connected(room: Room) -> tuple[dict[int, tuple[Satellite, Announcer]], FakeConnection]:
    conn = FakeConnection()
    return {room.echo: (room.satellite, conn)}, conn


def wait_out(url: str, wake: int) -> None:
    age(url, wake, "delivery_tried_at", int(WAKES.device_retry_s) + 1)


def test_a_room_reminder_runs_on_the_satellites_thread_and_is_said_there_when_it_is_connected(
        db_url: str, house: None, clips: FakeClips, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            wake = await fired(w, "room", room.echo)
            assert w.answers() == [(f"device:{room.echo}", SAYS.spoken)]
            prompt = str(w.model.prompts[0])
            assert "said aloud in the kitchen" in prompt and "It goes to their phone" not in prompt
            links, conn = connected(room)
            sender = FakeSender()
            assert await push_reminders.deliver(sender, PUSH) == 0
            assert await voice_reminders.deliver(links, PIPE) == 1
            assert clips.added == [(room.echo, SAYS.spoken, 0)] and len(conn.announced) == 1
            assert state(db_url, wake) == ("delivered", 1) and sender.sends == []
            assert await voice_reminders.deliver(links, PIPE) == 0
    run(go())


def test_a_satellite_not_connected_is_tried_its_tries_then_the_reminder_is_pushed_to_the_phone(
        db_url: str, house: None, clips: FakeClips, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            wake = await fired(w, "room", room.echo)
            sender = FakeSender()
            for attempt in range(1, WAKES.device_tries + 1):
                assert await voice_reminders.deliver({}, PIPE) == 1
                assert state(db_url, wake) == ("undelivered", attempt)
                assert await voice_reminders.deliver({}, PIPE) == 0, "not again before device_retry_s"
                assert await push_reminders.deliver(sender, PUSH) == 0, "the phone waits for the room's tries"
                wait_out(db_url, wake)
            assert await voice_reminders.deliver({}, PIPE) == 0
            assert await push_reminders.deliver(sender, PUSH) == 1
            assert [n.body for _, n in sender.sends] == [SAYS.spoken] and clips.added == []
            assert state(db_url, wake) == ("delivered", WAKES.device_tries + 1)
    run(go())


def test_a_singleton_taking_over_mid_tries_resumes_from_the_stored_tries_and_two_at_once_try_once(
        db_url: str, house: None, clips: FakeClips) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            wake = await fired(w, "room", room.echo)
            assert await voice_reminders.deliver({}, PIPE) == 1   # the pod that held the lease, satellite away
            wait_out(db_url, wake)
            links, conn = connected(room)                         # a new holder, the satellite back
            tried = await asyncio.gather(voice_reminders.deliver(links, PIPE), voice_reminders.deliver(links, PIPE))
            assert sorted(tried) == [0, 1] and len(conn.announced) == 1
            assert state(db_url, wake) == ("delivered", 2)
    run(go())


def test_a_screen_reminder_runs_on_the_screens_thread_and_counts_as_shown_while_a_screen_of_it_is_open(
        db_url: str, house: None, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            wake = await fired(w, "screen", room.hall)
            assert w.answers() == [(f"device:{room.hall}", SAYS.text)]
            assert "on the screen in the hallway" in str(w.model.prompts[0])
            assert await screen_delivery.deliver() == 1 and state(db_url, wake) == ("undelivered", 1)
            room.screens.shown.add(room.hall)
            wait_out(db_url, wake)
            assert await screen_delivery.deliver() == 1 and state(db_url, wake) == ("delivered", 2)
            assert await push_reminders.deliver(FakeSender(), PUSH) == 0
    run(go())


def test_a_screen_left_off_sends_the_reminder_to_the_phone_after_its_tries(
        db_url: str, house: None, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            wake = await fired(w, "screen", room.hall)
            for _ in range(WAKES.device_tries):
                assert await screen_delivery.deliver() == 1
                wait_out(db_url, wake)
            assert await screen_delivery.deliver() == 0
            sender = FakeSender()
            assert await push_reminders.deliver(sender, PUSH) == 1 and len(sender.sends) == 1
            assert state(db_url, wake) == ("delivered", WAKES.device_tries + 1)
    run(go())


def test_a_device_removed_before_it_fires_sends_the_reminder_to_the_phone(
        db_url: str, house: None, subscriptions: FakeSubscriptions) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            subscriptions.rows.append(Subscription(1, w.home, w.alana, browser()))
            wake = await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, "zq brief", datetime.now(UTC), None,
                                                   route="room", device_id=room.echo))
            scalar(db_url, "WITH d AS (DELETE FROM devices WHERE id = %s RETURNING 1) SELECT count(*) FROM d", (room.echo,))
            w.model.script = [SAYS]
            await runner.sweep()
            assert w.answers() == [(f"push:{w.alana}", SAYS.text)]
            assert await voice_reminders.deliver({}, PIPE) == 0
            sender = FakeSender()
            assert await push_reminders.deliver(sender, PUSH) == 1 and state(db_url, wake) == ("delivered", 1)
    run(go())


@pytest.mark.parametrize(("delivery", "pick", "ok"), [
    ("room", "echo", True), ("screen", "hall", True), ("room", "hall", False), ("screen", "echo", False),
    ("room", "elsewhere", False), ("room", "none", False), ("phone", "echo", False)])
def test_the_tool_takes_a_device_that_fits_the_route_from_the_households_own(
        db_url: str, house: None, delivery: str, pick: str, ok: bool) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            elsewhere = device(db_url, household(db_url), "zq other")
            ids = {"echo": room.echo, "hall": room.hall, "elsewhere": elsewhere, "none": None}
            tools = ReminderTools(w.home, w.alana, private=True, routable=partial(reminder_device.takes, w.home))
            args: dict[str, object] = {"for": "Alana", "at": "2099-01-01T08:00", "what": "zq", "delivery": delivery}
            if ids[pick] is not None:
                args["device"] = ids[pick]
            result = await tools.call(ToolCall("t1", "remind", args))
            assert result.is_error is not ok, result.content
            routed = scalar(db_url, "SELECT coalesce(json_agg(json_build_array(route, route_device_id)), '[]') FROM wakes")
            assert routed == ([[delivery, ids[pick]]] if ok else [])
    run(go())


def test_without_a_device_check_no_room_or_screen_can_be_set(db_url: str, house: None) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            room = furnished(w)
            tools = ReminderTools(w.home, w.alana, private=True)
            result = await tools.call(ToolCall("t1", "remind", {"for": "Alana", "at": "2099-01-01T08:00", "what": "zq",
                                                                "delivery": "room", "device": room.echo}))
            assert result.is_error
    run(go())
