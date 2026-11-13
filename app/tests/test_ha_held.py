"""HeldStates over a stand-in Home Assistant (`ha_held_support`): while held, a thing asked about is subscribed by a
state trigger and read once, then answered from what the house tells; a dropped socket comes back after backoff,
subscribes again and reads again, so a change during the gap is caught; a thing left unasked is let go; a household
whose connection changed gets a new socket; and when not held each thing is read once over REST."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from ashley import services
from ashley.logs import Logfmt
from ashley.home_assistant.ha_held import SocketStates, load
from ashley.home_assistant.held_states import EntityState
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import HouseUnavailable
from ashley.home_assistant.house_settings import load as load_house
from ha_held_support import SETTINGS, Clock, FakeHa, FakeHomes, Naps, home_of, until

DOOR, DRYER = "binary_sensor.back_door", "sensor.dryer_status"
@dataclass
class Held:
    ha: FakeHa
    states: SocketStates
    homes: FakeHomes
    naps: Naps
    clock: Clock
    nudges: list[int]


@asynccontextmanager
async def held(ha: FakeHa) -> AsyncGenerator[Held]:
    naps, clock, nudges = Naps(), Clock(), list[int]()
    states = SocketStates(SETTINGS, load_house(), naps, clock)
    async with home_of(ha) as home:
        homes = FakeHomes(home)
        services.register(Homes, homes)
        holding = asyncio.create_task(states.hold(lambda: nudges.append(1)))
        await asyncio.sleep(0)
        try:
            yield Held(ha, states, homes, naps, clock, nudges)
        finally:
            holding.cancel()
            with pytest.raises(asyncio.CancelledError):
                await holding
            services.unregister(Homes)


def go(scenario: Callable[[], Awaitable[None]]) -> None:
    asyncio.run(asyncio.wait_for(scenario(), 5))


def lines(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(Logfmt().format(r) for r in caplog.records)


def test_a_thing_asked_about_is_subscribed_by_a_state_trigger_and_read_once() -> None:
    ha = FakeHa({DOOR: "off"}, {DOOR: "Back door"})

    async def scenario() -> None:
        async with held(ha) as h:
            got = await h.states.states(1, [DOOR, "sensor.not_there"])
            assert got == {DOOR: EntityState("off", "Back door"), "sensor.not_there": None}
            subscribe = [c for c in ha.commands if c["type"] == "subscribe_trigger"]
            assert [c["trigger"] for c in subscribe] == [
                {"platform": "state", "entity_id": DOOR, "to": None},
                {"platform": "state", "entity_id": "sensor.not_there", "to": None}]
            await h.states.states(1, [DOOR])
            assert sum(c["type"] == "get_states" for c in ha.commands) == 1 and ha.connections == 1
    go(scenario)


def test_a_change_the_house_tells_is_what_the_next_ask_answers_and_it_nudges() -> None:
    ha = FakeHa({DOOR: "off"})

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.states(1, [DOOR])
            before = len(h.nudges)
            await ha.change(DOOR, "on")
            await until(lambda: len(h.nudges) > before, "a nudge")
            assert await h.states.states(1, [DOOR]) == {DOOR: EntityState("on", DOOR)}
            await ha.change(DOOR, None)
            await until(lambda: len(h.nudges) > before + 1, "a second nudge")
            assert await h.states.states(1, [DOOR]) == {DOOR: None}
            assert sum(c["type"] == "get_states" for c in ha.commands) == 1
    go(scenario)


def test_a_drop_reconnects_after_backoff_subscribes_again_and_reads_the_change_made_meanwhile(
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ha = FakeHa({DOOR: "off", DRYER: "running"})

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.states(1, [DOOR, DRYER])
            await ha.drop()
            await until(lambda: h.naps.taken, "a backoff")
            with pytest.raises(HouseUnavailable):
                await h.states.states(1, [DOOR])
            ha.states[DRYER] = "idle"
            nudged = len(h.nudges)
            h.naps.free = 1
            await until(lambda: len(h.nudges) > nudged, "a nudge on return")
            assert ha.connections == 2 and ha.subscribed() == [DOOR, DRYER]
            assert await h.states.states(1, [DRYER]) == {DRYER: EntityState("idle", DRYER)}
            assert h.naps.taken[0] == SETTINGS.backoff_s
    go(scenario)
    out = lines(caplog)
    assert "event=ha_held.dropped household=1" in out and "subscriptions=2" in out
    assert "event=ha_held.resubscribed household=1 entities=2" in out
    assert "back_door" not in out and "dryer" not in out and "made-up-token" not in out


def test_a_house_that_refuses_backs_off_doubling_asks_fail_at_once_meanwhile_and_a_good_session_resets_it() -> None:
    ha = FakeHa({DOOR: "off"}, refuse=True)

    async def scenario() -> None:
        async with held(ha) as h:
            with pytest.raises(HouseUnavailable):
                await h.states.states(1, [DOOR])
            h.naps.free = 5
            await until(lambda: len(h.naps.taken) >= 6, "six backoffs")
            assert h.naps.taken[:6] == [1, 2, 4, 8, 8, 8]
            ha.refuse, nudged = False, len(h.nudges)
            h.naps.free = 1
            await until(lambda: len(h.nudges) > nudged, "a session that came up")
            await ha.drop()
            await until(lambda: len(h.naps.taken) == 7, "the backoff after it")
            assert h.naps.taken[6] == SETTINGS.backoff_s
    go(scenario)


def test_a_thing_left_unasked_for_idle_s_is_let_go() -> None:
    ha = FakeHa({DOOR: "off", DRYER: "idle"})

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.states(1, [DOOR, DRYER])
            h.clock.now += SETTINGS.idle_s / 2
            await h.states.states(1, [DOOR])
            h.clock.now += SETTINGS.idle_s / 2 + 1
            await h.states.states(1, [DOOR])
            assert ha.subscribed() == [DOOR]
            assert [c["type"] for c in ha.commands].count("unsubscribe_events") == 1
    go(scenario)


def test_a_replaced_connection_gets_a_new_socket_and_a_household_with_none_gets_none() -> None:
    ha = FakeHa({DOOR: "off"})

    async def scenario() -> None:
        async with home_of(ha) as replaced, held(ha) as h:
            await h.states.states(1, [DOOR])
            h.homes.home = replaced
            await h.states.states(1, [DOOR])
            assert ha.connections == 2
            assert await h.states.states(2, [DOOR]) is None
    go(scenario)


def test_when_not_held_each_thing_is_read_once_over_rest() -> None:
    ha = FakeHa({DOOR: "on"}, {DOOR: "Back door"})

    async def scenario() -> None:
        async with home_of(ha) as home:
            services.register(Homes, FakeHomes(home))
            try:
                got = await SocketStates(SETTINGS).states(1, [DOOR, "sensor.gone"])
            finally:
                services.unregister(Homes)
            assert got == {DOOR: EntityState("on", "Back door"), "sensor.gone": None}
            assert ha.rest == 2 and ha.connections == 0
    go(scenario)


def test_the_shipped_tunables_load() -> None:
    settings = load()
    assert 0 < settings.backoff_s <= settings.max_backoff_s and settings.idle_s > 0 and settings.ping_s > 0
