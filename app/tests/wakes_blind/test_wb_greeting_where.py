"""Where an arrival greeting is said: Initiative places it at the satellite of the place the wake names, else at the
screen there, else the phone, over the real runner, turn loop and wakes table; the singletons that deliver reminders
deliver it, and the phone has it after the device's tries. A device is found by its form and configured place, never
its name; quiet plans place nothing."""

import pytest
from ashley import services
from ashley.channels.model import Device, Listed, Satellite
from ashley.channels.push import reminders as push_reminders
from ashley.channels.push.config import load as push_config
from ashley.channels.push.subscriptions import Subscription
from ashley.channels.voice import reminders as voice_reminders
from ashley.channels.voice.connection import Announcer
from ashley.channels.wake import reminder_device, screen_delivery
from ashley.channels.wake.config import CONFIG as WAKES
from ashley.initiative.initiative import Scored
from ashley.initiative.moment import Candidate, Moment
from ashley.initiative.score import planned
from ashley.initiative.weights import parse
from ashley.live.screens import Screens
from contract.conversations_support import run, scalar
from contract.test_inflight_resume import World
from initiative_support import FLOOR, weights
from later_support import FakeClips, clips as clips
from push_support import FakeSender, FakeSubscriptions, browser, subscriptions as subscriptions
from test_reminder_in_room import OpenScreens
from voice_support import FakeConnection, FakeTurnLoop, pipeline
from wb_runner_support import DONE, SILENT, stack, sweep
from wb_support import add_device

PIPE = pipeline(FakeTurnLoop())
PUSH = push_config()


def at(world: World, name: str, place: str, medium: str = "text") -> Device:
    """A device row in the database, as the household's list shows it."""
    household = world.who.household_id
    return Device(add_device(world.url, household, f"zq-{name}", name), household, name, place, "present",
                  "spoken" if medium == "spoken" else "text", "command" if medium == "spoken" else "chat")


def listed(*rows: Listed) -> dict[int, list[Listed]]:
    return {rows[0].device.household_id: list(rows)}


def routed(world: World, wake_id: int) -> tuple[str, int | None, str | None, int]:
    got = scalar(world.url, "SELECT json_build_array(route, route_device_id, delivery, coalesce(person_id, 0)) "
                            "FROM wakes WHERE id = %s", (wake_id,))
    return got[0], got[1], got[2], got[3]


def threads(world: World) -> list[str]:
    got = scalar(world.url, "SELECT coalesce(json_agg(ct.thread ORDER BY t.id), '[]') FROM turns t "
                            "JOIN conversation_threads ct ON ct.conversation_id = t.conversation_id "
                            "WHERE t.author = 'ashley' AND NOT t.follows")
    return list(got)


def wait_out(world: World, wake_id: int) -> None:
    scalar(world.url, "WITH u AS (UPDATE wakes SET delivery_tried_at = delivery_tried_at - make_interval(secs => %s) "
                      "WHERE id = %s RETURNING 1) SELECT count(*) FROM u", (WAKES.device_retry_s + 1, wake_id))


def test_a_greeting_for_a_place_with_a_satellite_is_said_there_and_not_queued_for_the_phone(
        world: World, clips: FakeClips) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        rows: dict[int, list[Listed]] = {}
        async with stack(world, rows=rows) as s:
            echo = at(world, "echo", "Back Hall", "spoken")
            rows.update(listed(Listed(echo, "satellite")))
            await s.rule(greets=True)
            wake = await s.hand_in(what="back_hall")
            await sweep()
            assert routed(world, wake) == ("room", echo.id, "sending", world.who.id)
            assert threads(world) == [f"device:{echo.id}"] and s.queued() == 0
            assert "said aloud in the Back Hall" in str(world.first.inference.prompts[0])
            conn = FakeConnection()
            links: dict[int, tuple[Satellite, Announcer]] = {echo.id: (Satellite(echo, "zq-echo.invalid", None), conn)}
            assert await voice_reminders.deliver(links, PIPE) == 1
            assert len(conn.announced) == 1 and routed(world, wake)[2] == "delivered"

    run(go())


def test_a_greeting_for_a_place_with_only_the_kiosk_is_shown_there(world: World) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        rows: dict[int, list[Listed]] = {}
        async with stack(world, rows=rows) as s:
            tablet = at(world, "tablet", "hallway")
            rows.update(listed(Listed(tablet, "other")))
            screens = OpenScreens({tablet.id})
            services.register(Screens, screens)
            await s.rule(greets=True)
            wake = await s.hand_in(what="hallway")
            await sweep()
            assert routed(world, wake) == ("screen", tablet.id, "sending", world.who.id)
            assert threads(world) == [f"device:{tablet.id}"] and s.queued() == 0
            assert await screen_delivery.deliver() == 1 and routed(world, wake)[2] == "delivered"
        services.unregister(Screens)

    run(go())


def test_the_satellite_is_chosen_over_the_screen_of_the_same_place() -> None:
    echo, tablet = Candidate("room", 1), Candidate("screen", 2)
    for devices in ((tablet, echo), (echo, tablet)):
        plan = planned(Moment("wake:1", devices=devices), parse(weights()))
        assert (plan.route, plan.device_id) == ("room", 1)
    assert planned(Moment("wake:1", devices=(tablet,)), parse(weights())).route == "screen"
    assert planned(Moment("wake:1"), parse(weights())).route is None


@pytest.mark.parametrize("place", ["kitchen", None, "front_door"])
def test_a_greeting_with_no_device_at_its_place_goes_to_the_phone_as_before(world: World, place: str | None) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        rows: dict[int, list[Listed]] = {}
        async with stack(world, rows=rows) as s:
            echo = at(world, "echo", "Kitchen", "spoken")
            rows.update(listed(Listed(echo, "satellite")))
            await s.rule(greets=True)
            wake = await s.hand_in(what=place)
            await sweep()
            if place == "kitchen":
                assert routed(world, wake)[0] == "room", "control: a device at the place takes it"
                return
            assert routed(world, wake) == ("phone", None, None, 0)
            assert threads(world) == [f"push:{world.who.id}"] and s.queued() == 1

    run(go())


def test_a_device_is_found_by_its_form_and_place_never_its_name() -> None:
    household = 1
    rows = [Listed(Device(1, household, "kitchen echo", "den", "present", "spoken", "command"), "satellite"),
            Listed(Device(2, household, "den", "Den", "present", "text", "chat"), "discord_server"),
            Listed(Device(3, household, "kitchen", "Den", "present", "text", "chat"), "house"),
            Listed(Device(4, household, "tablet", "DEN", "present", "text", "chat"), "other")]
    assert reminder_device.at_place(rows, "den") == (Candidate("room", 1), Candidate("screen", 4))
    assert reminder_device.at_place(rows, None) == () and reminder_device.at_place(rows, "kitchen") == ()


def test_a_quiet_plan_places_nothing_and_keeps_her_reply_quiet(world: World) -> None:
    world.first.inference.script = [SILENT]
    world.as_pod(world.first)

    async def go() -> None:
        rows: dict[int, list[Listed]] = {}
        async with stack(world, Scored(parse(weights(odds=[{"from": FLOOR, "full": 0.0, "short": 0.0, "silent": 1.0}]))), rows) as s:
            echo = at(world, "echo", "kitchen", "spoken")
            rows.update(listed(Listed(echo, "satellite")))
            await s.rule(greets=True)
            wake = await s.hand_in(what="kitchen")
            await sweep()
            assert routed(world, wake) == ("phone", None, None, 0) and s.queued() == 0

    run(go())


def test_a_satellite_not_connected_hands_the_greeting_to_the_phone_after_its_tries(
        world: World, clips: FakeClips, subscriptions: FakeSubscriptions) -> None:
    world.first.inference.script = [DONE]
    world.as_pod(world.first)

    async def go() -> None:
        rows: dict[int, list[Listed]] = {}
        async with stack(world, rows=rows) as s:
            echo = at(world, "echo", "kitchen", "spoken")
            rows.update(listed(Listed(echo, "satellite")))
            subscriptions.rows.append(Subscription(1, world.who.household_id, world.who.id, browser()))
            await s.rule(greets=True)
            wake = await s.hand_in(what="kitchen")
            await sweep()
            sender = FakeSender()
            for _ in range(WAKES.device_tries):
                assert await voice_reminders.deliver({}, PIPE) == 1
                assert await push_reminders.deliver(sender, PUSH) == 0
                wait_out(world, wake)
            assert await push_reminders.deliver(sender, PUSH) == 1
            assert [n.body for _, n in sender.sends] == [DONE.text] and routed(world, wake)[2] == "delivered"

    run(go())


def test_two_arrivals_are_two_greetings_each_placed_for_its_own_wake(world: World) -> None:
    world.first.inference.script = [DONE, DONE]
    world.as_pod(world.first)

    async def go() -> None:
        rows: dict[int, list[Listed]] = {}
        async with stack(world, rows=rows) as s:
            echo = at(world, "echo", "kitchen", "spoken")
            rows.update(listed(Listed(echo, "satellite")))
            await s.rule(greets=True)
            first, second = await s.hand_in("ctx-1", what="kitchen"), await s.hand_in("ctx-2", what="kitchen")
            await sweep()
            assert [routed(world, w)[:2] for w in (first, second)] == [("room", echo.id)] * 2

    run(go())


