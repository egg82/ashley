"""HeldStates' event subscriptions over a stand-in Home Assistant (`ha_held_support`): while held, each event of a held
type is handed to its recorder with its data, time and context; a type no longer named is let go; a dropped socket
subscribes the held types again; a recorder that raises loses that event and nothing else; and when nothing holds, or
the house is unreachable, asking fails at once."""

import asyncio
import logging
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.home_assistant.ha_held import SocketStates
from ashley.home_assistant.held_states import HouseEvent
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import HouseUnavailable
from ashley.home_assistant.house_settings import load as load_house
from ha_held_support import SETTINGS, Clock, FakeHa, FakeHomes, Naps, home_of, until
from test_ha_held import go, held, lines


class Heard:
    def __init__(self) -> None:
        self.events: list[HouseEvent] = []

    async def __call__(self, event: HouseEvent) -> None:
        self.events.append(event)


def test_an_event_of_a_held_type_is_handed_to_its_recorder_with_its_time_and_context() -> None:
    ha, shadow, other = FakeHa(), Heard(), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.events("t", 1, {"ashley_shadow": shadow, "automation_triggered": other})
            assert ha.event_types() == ["ashley_shadow", "automation_triggered"]
            await ha.fire("ashley_shadow", {"bench": 3, "piece": 1, "version": 2}, context="abc")
            await ha.fire("something_else", {})
            await until(lambda: shadow.events, "the event")
            got = shadow.events[0]
            assert (got.type, dict(got.data), got.context) == ("ashley_shadow", {"bench": 3, "piece": 1, "version": 2}, "abc")
            assert got.at == datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
            assert other.events == [] and len(shadow.events) == 1
    go(scenario)


def test_asking_again_changes_the_held_types_and_lets_go_of_the_ones_dropped() -> None:
    ha, shadow = FakeHa(), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.events("t", 1, {"ashley_shadow": shadow, "automation_triggered": Heard()})
            await h.states.events("t", 1, {"ashley_shadow": shadow})
            assert ha.event_types() == ["ashley_shadow"]
            subscribed = len([c for c in ha.commands if c["type"] == "subscribe_events"])
            await h.states.events("t", 1, {"ashley_shadow": shadow})
            assert len([c for c in ha.commands if c["type"] == "subscribe_events"]) == subscribed
            await h.states.events("t", 1, {})
            assert ha.event_types() == []
            await ha.fire("ashley_shadow", {})
            await asyncio.sleep(0)
            assert shadow.events == []
    go(scenario)


def test_two_owners_hold_their_own_types_and_neither_lets_go_of_the_other() -> None:
    ha, mine, theirs, both = FakeHa(), Heard(), Heard(), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.events("a", 1, {"one": mine, "shared": both})
            await h.states.events("b", 1, {"two": theirs, "shared": both})
            assert ha.event_types() == ["one", "shared", "two"]
            await h.states.events("a", 1, {})
            assert ha.event_types() == ["shared", "two"]
            await ha.fire("shared", {})
            await ha.fire("two", {})
            await until(lambda: theirs.events and both.events, "b's events")
            assert [len(both.events), len(theirs.events), len(mine.events)] == [1, 1, 0]
            await h.states.events("a", 1, {"shared": mine})
            await ha.fire("shared", {})
            await until(lambda: len(both.events) == 2 and mine.events, "both owners told")
            await h.states.events("b", 1, {})
            assert ha.event_types() == ["shared"]
    go(scenario)


def test_a_dropped_socket_subscribes_the_held_types_again() -> None:
    ha, shadow = FakeHa(), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.events("t", 1, {"ashley_shadow": shadow})
            await ha.drop()
            await until(lambda: h.naps.taken, "a backoff")
            h.naps.free = 1
            await until(lambda: ha.connections == 2 and ha.event_types() == ["ashley_shadow"], "the type again")
            await ha.fire("ashley_shadow", {"piece": 1})
            await until(lambda: shadow.events, "an event on the new socket")
    go(scenario)


def test_a_recorder_that_raises_loses_that_event_and_is_logged_without_its_data(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ha, good = FakeHa(), Heard()
    calls: list[int] = []

    async def bad(event: HouseEvent) -> None:
        calls.append(1)
        raise RuntimeError("made-up secret detail")

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.events("t", 1, {"ashley_shadow": bad, "automation_triggered": good})
            await ha.fire("ashley_shadow", {"piece": 9})
            await ha.fire("automation_triggered", {"entity_id": "automation.x"})
            await until(lambda: good.events, "the next event")
            assert calls == [1]
    go(scenario)
    out = lines(caplog)
    assert "event=ha_held.event_lost household=1 reason=RuntimeError" in out and "made-up" not in out and "automation.x" not in out


def test_asking_fails_at_once_when_nothing_holds_or_the_house_refuses() -> None:
    async def not_held() -> None:
        async with home_of(FakeHa()) as home:
            services.register(Homes, FakeHomes(home))
            try:
                with pytest.raises(HouseUnavailable):
                    await SocketStates(SETTINGS, load_house(), Naps(), Clock()).events("t", 1, {"ashley_shadow": Heard()})
            finally:
                services.unregister(Homes)

    async def refused() -> None:
        async with held(FakeHa(refuse=True)) as h:
            with pytest.raises(HouseUnavailable):
                await h.states.events("t", 1, {"ashley_shadow": Heard()})

    go(not_held)
    go(refused)
