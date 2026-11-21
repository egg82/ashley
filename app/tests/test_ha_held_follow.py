"""HeldStates' followed things over a stand-in Home Assistant (`ha_held_support`): a state trigger on exactly the things
named, each change handed to its owner's recorder with the new state's attributes; an owner's set replaces only its own;
a dropped socket follows again; a recorder that raises loses that change and nothing else. The message shape is Home
Assistant's `subscribe_trigger` event (`websocket_api/commands.py`, `handle_subscribe_trigger`: `variables.trigger`
with `to_state`, and the context)."""

import logging

import pytest
from ashley.home_assistant.held_states import StateChange
from ha_held_support import FakeHa, until
from test_ha_held import go, held, lines

BELL, OTHER = "event.front_bell", "event.back_door_events"


class Heard:
    def __init__(self) -> None:
        self.changes: list[StateChange] = []

    async def __call__(self, change: StateChange) -> None:
        self.changes.append(change)


def test_a_followed_thing_is_handed_with_its_new_attributes_and_nothing_else_is_subscribed() -> None:
    ha, heard = FakeHa({BELL: "unknown", OTHER: "unknown"}), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.follow("cameras", 1, [BELL], heard)
            assert ha.subscribed() == [BELL]
            ha.attributes[BELL] = {"event_type": "ring"}
            await ha.change(BELL, "2026-11-21T10:00:05.123+00:00")
            await ha.change(OTHER, "x")
            await until(lambda: heard.changes, "the change")
            got = heard.changes[0]
            assert (got.entity_id, got.state, got.attributes["event_type"]) == (BELL, "2026-11-21T10:00:05.123+00:00", "ring")
            assert len(heard.changes) == 1
    go(scenario)


def test_two_owners_follow_their_own_things_and_a_shared_one_goes_to_both() -> None:
    ha, mine, theirs = FakeHa({BELL: "a", OTHER: "a"}), Heard(), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.follow("a", 1, [BELL], mine)
            await h.states.follow("b", 1, [BELL, OTHER], theirs)
            assert ha.subscribed() == sorted([BELL, OTHER])
            await h.states.follow("a", 1, [], mine)
            assert ha.subscribed() == sorted([BELL, OTHER])
            await h.states.follow("b", 1, [OTHER], theirs)
            assert ha.subscribed() == [OTHER]
            await h.states.follow("a", 1, [BELL, OTHER], mine)
            await ha.change(OTHER, "b")
            await until(lambda: mine.changes and theirs.changes, "both told")
    go(scenario)


def test_a_dropped_socket_follows_again() -> None:
    ha, heard = FakeHa({BELL: "a"}), Heard()

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.follow("a", 1, [BELL], heard)
            await ha.drop()
            await until(lambda: h.naps.taken, "a backoff")
            h.naps.free = 1
            await until(lambda: ha.connections == 2 and ha.subscribed() == [BELL], "followed again")
            await ha.change(BELL, "b")
            await until(lambda: heard.changes, "a change on the new socket")
    go(scenario)


def test_a_recorder_that_raises_loses_that_change_and_is_logged_without_its_data(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ha, good = FakeHa({BELL: "a"}), Heard()

    async def bad(change: StateChange) -> None:
        raise RuntimeError("made-up secret detail")

    async def scenario() -> None:
        async with held(ha) as h:
            await h.states.follow("a", 1, [BELL], bad)
            await h.states.follow("b", 1, [BELL], good)
            await ha.change(BELL, "b")
            await until(lambda: good.changes, "the other owner told")
    go(scenario)
    out = lines(caplog)
    assert "event=ha_held.event_lost household=1 reason=RuntimeError" in out and "made-up" not in out and BELL not in out
