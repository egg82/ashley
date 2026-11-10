"""Her house tools (`tools.house_tools.HouseTools`) over a recording House: reads are never gated, `house_do` runs what
is everyday and refuses outright what `irreversible.json` covers, and nothing she is shown reaches the log."""

import logging
from typing import Any

import pytest
from ashley.home_assistant import irreversible
from ashley.home_assistant.house import ActionInfo, Record, State
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_act import Rules
from ashley.tools.house_change import CHANGE, CONFIRM
from ashley.tools.house_tools import HouseTools
from contract.conversations_support import run
from hag_world_support import RecordingHouse


STATES = (State("light.porch", "Porch light", "off", "light", "Garden", {}, None, ("veranda",), (), True),
          State("light.attic", "Attic light", "on", "light", None, {}, None, (), (), False))
CALENDAR = (ActionInfo("calendar.get_events", "Events", {"duration": "How long"}, "only"),
            ActionInfo("light.turn_on", "On", {}, "none"))


def house_tools(house: RecordingHouse) -> HouseTools:
    rules = Rules(excluded=("assist_satellite.announce",), reads=(), irreversible=irreversible.load())
    return HouseTools(house, rules, house_look_config.load(), house_state_config.load())


async def use(t: HouseTools, tool: str, /, **arguments: Any) -> ToolResult:
    return await t.call(ToolCall("c2", tool, arguments))


def test_her_house_tools_are_offered_with_the_reads_marked_as_reads() -> None:
    async def go() -> None:
        specs = {s.name: s for s in (await house_tools(RecordingHouse(STATES)).catalogue()).specs}
        assert {"house_state", "house_find", "house_history", "house_ask", "house_do"} <= set(specs)
        assert all(specs[n].reads for n in ("house_state", "house_find", "house_history", "house_ask"))
        assert specs["house_do"].reads is False
        assert CHANGE not in specs and CONFIRM not in specs
    run(go())


def test_reads_are_never_gated_and_ask_for_data_runs_the_action_at_once() -> None:
    async def go() -> None:
        family = State("calendar.family", "Family", "off", "calendar", None, {}, None, (), (), True)
        house = RecordingHouse((*STATES, family), rows={"area": (Record("area", "garden", "Garden", {}),)}, catalogue=CALENDAR)
        house.returns = {"calendar.family": {"events": []}}
        t = house_tools(house)
        for name, arguments in (("house_state", {"name": "porch"}), ("house_state", {"all": True}),
                                ("house_find", {"kind": "area"}), ("house_find", {"kind": "action"}),
                                ("house_history", {"ids": ["light.porch"]}), ("house_history", {"kind": "logbook"})):
            got = await use(t, name, **arguments)
            assert not got.is_error, (name, arguments, got.content)
        state = await use(t, "house_state", name="porch")
        assert "Porch light" in state.content and "Attic light" not in state.content
        asked = await use(t, "house_ask", action="calendar.get_events", ids=["calendar.family"], data='{"duration": 3}')
        assert not asked.is_error
        assert house.calls == [("perform", ("calendar.get_events", ("calendar.family",), {"duration": 3}))]
    run(go())


def test_house_do_runs_an_everyday_action_and_refuses_what_needs_a_persons_ok_outright() -> None:
    async def go() -> None:
        house = RecordingHouse(STATES, catalogue=CALENDAR)
        t = house_tools(house)
        done = await use(t, "house_do", action="light.turn_on", ids=["light.porch"], data='{"brightness_pct": 20}')
        assert not done.is_error
        assert house.calls == [("perform", ("light.turn_on", ("light.porch",), {"brightness_pct": 20}))]
        house.calls.clear()
        for action in ("homeassistant.restart", "homeassistant.stop", "recorder.purge", "backup.create", "hassio.host_reboot"):
            refused = await use(t, "house_do", action=action, ids=["light.porch"])
            assert refused.is_error or "not" in refused.content.lower(), action
        assert house.calls == []
    run(go())


def test_house_do_on_a_name_that_matches_nothing_does_nothing_and_says_so() -> None:
    async def go() -> None:
        house = RecordingHouse(STATES, catalogue=CALENDAR)
        t = house_tools(house)
        for arguments in ({"name": "garage"}, {"ids": ["light.nowhere"]}):
            got = await use(t, "house_do", action="light.turn_on", **arguments)
            assert got.is_error, arguments
        assert house.calls == []
    run(go())


def test_house_ask_does_not_run_an_action_that_needs_a_persons_ok() -> None:
    async def go() -> None:
        house = RecordingHouse(STATES, catalogue=CALENDAR)
        t = house_tools(house)
        await use(t, "house_ask", action="homeassistant.restart")
        await use(t, "house_ask", action="backup.create")
        asked = await use(t, "house_ask", action="light.turn_on", ids=["light.porch"])
        assert asked.is_error
        assert house.calls == []
    run(go())


def test_what_the_house_holds_is_not_logged_by_her_tools(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    shown = (State("light.marker_6611", "Marker name 6611", "marker-state-6611", "light", "Marker area 6611",
                   {"note": "marker-attribute-6611"}, None, ("marker-alias-6611",), (), True),)

    async def go() -> None:
        house = RecordingHouse(shown, catalogue=CALENDAR)
        t = house_tools(house)
        await t.catalogue()
        await use(t, "house_state", name="marker")
        await use(t, "house_find", kind="entity", name="marker")
        await use(t, "house_do", action="light.turn_on", ids=["light.marker_6611"], data='{"note": "marker-data-6611"}')
        await use(t, "house_do", action="backup.create", data='{"note": "marker-data-6611"}')
    run(go())
    lines = [f"{r.name} {r.getMessage()} {r.__dict__}" for r in caplog.records if r.name.startswith("ashley")]
    assert any("house_do" in line for line in lines), "nothing was logged, so the probe could see nothing"
    for secret in ("marker_6611", "Marker name 6611", "marker-state-6611", "Marker area 6611", "marker-attribute-6611",
                   "marker-alias-6611", "marker-data-6611"):
        assert not any(secret in line for line in lines), secret
