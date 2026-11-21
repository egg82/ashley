"""The calendar port and her `calendar_events` tool over Home Assistant's adapter, against an in-memory house: nothing is
offered to a household with no calendar source or with the port switched off; events come back in the household's own
time, soonest first, each calendar labelled with its source and visibility; a source that cannot answer is `unread`,
never an empty day; bad arguments ask the house nothing; and the tool is offered to a known speaker in any chat."""

import asyncio
import json
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley import services
from ashley.calendars.calendars import Calendars
from ashley.calendars.routed import RoutedCalendars
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.connections.model import Port
from ashley.connections.settings import SettingValues
from ashley.connections.settings_read import NullSettingsReader, SettingsReader
from ashley.home_assistant.calendars import HaCalendars, NAME
from ashley.home_assistant.homes import Homes
from ashley.inference.model import ToolCall, ToolResult
from ashley.people.people import People
from ashley.tools import calendar_config
from ashley.tools.calendar_specs import EVENTS
from ashley.tools.calendar_tools import CalendarTools
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from money_support import HeldConnections
from respond_support import HOME, FakePeople

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)
CONFIG = calendar_config.load()
FAMILY, SCHOOL = "calendar.zq_family", "calendar.zq_school"


class Switches(NullSettingsReader):
    def __init__(self, values: SettingValues, off: frozenset[str] = frozenset()) -> None:
        self.values, self.off = values, off

    async def of(self, household_id: int, port: Port) -> SettingValues:
        return self.values

    async def ports_off(self, household_id: int) -> Mapping[int, frozenset[str]]:
        return {1: self.off} if self.off else {}


def _event(summary: str, start: str, end: str | None = None, **more: str) -> dict[str, str]:
    return {"summary": summary, "start": start, "end": end or start, **more}


@pytest.fixture
def house() -> Iterator[MemoryHouse]:
    made = MemoryHouse()
    made.things = [state(FAMILY, "Family", "off"), state(SCHOOL, "School", "off"), state("light.zq", "Lamp", "on")]
    made.returns["calendar.get_events"] = {
        FAMILY: {"events": [_event("Soccer", "2026-11-13T16:30:00-07:00", "2026-11-13T17:30:00-07:00", location="Field 2"),
                            _event("Dentist", "2026-11-14T05:00:00-07:00")]},
        SCHOOL: {"events": [_event("Trash day", "2026-11-13", "2026-11-14")]}}
    held = HeldConnections()
    held.connect(HOME.id, "http://ha.test", "k", NAME)
    services.register(Connections, held)
    services.register(Homes, AnyHousehold(made))
    services.register(People, FakePeople())
    services.register(Calendars, RoutedCalendars({NAME: HaCalendars()}))
    services.register(SettingsReader, Switches({"discreet_calendars": [SCHOOL]}))
    yield made


def tools(household: int = HOME.id) -> CalendarTools:
    return CalendarTools(household, CONFIG, lambda: NOW)


def call(arguments: dict[str, object] | None = None, household: int = HOME.id) -> ToolResult:
    return asyncio.run(tools(household).call(ToolCall("c1", EVENTS, arguments or {})))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loose: dict[str, Any] = json.loads(result.content)
    return loose


def test_a_household_with_no_calendar_source_is_offered_nothing(house: MemoryHouse) -> None:
    assert asyncio.run(tools(HOME.id + 1).catalogue()).specs == ()


def test_the_one_tool_reads_and_is_outside(house: MemoryHouse) -> None:
    (spec,) = asyncio.run(tools().catalogue()).specs
    assert (spec.name, spec.reads, spec.outside) == (EVENTS, True, True)


def test_events_come_back_in_local_time_soonest_first_with_each_calendar_labelled(house: MemoryHouse) -> None:
    got = body(call({"days": 2}))
    assert [(e["title"], e["start"], e.get("all_day"), e["calendar"]) for e in got["events"]] == [
        ("Trash day", "2026-11-13", True, SCHOOL), ("Soccer", "2026-11-13 16:30", None, FAMILY),
        ("Dentist", "2026-11-14 05:00", None, FAMILY)]
    assert got["events"][1]["location"] == "Field 2" and got["events"][1]["end"] == "2026-11-13 17:30"
    assert got["calendars"] == [
        {"id": FAMILY, "title": "Family", "source": NAME, "visibility": "shared"},
        {"id": SCHOOL, "title": "School", "source": NAME, "visibility": "discreet"}]
    assert got["cut"] is False and "unread" not in got
    action, ids, data = house.done[0][2:]
    assert (action, ids) == ("calendar.get_events", (FAMILY, SCHOOL))
    assert (data["start_date_time"], data["end_date_time"]) == ("2026-11-13T00:00:00-07:00", "2026-11-15T00:00:00-07:00")


def test_one_calendar_by_id_asks_only_for_it_and_an_unknown_id_is_refused(house: MemoryHouse) -> None:
    house.returns["calendar.get_events"] = {FAMILY: {"events": []}}
    assert body(call({"calendar": FAMILY}))["calendars"][0]["id"] == FAMILY
    assert house.done[0][3] == (FAMILY,)
    house.done.clear()
    assert call({"calendar": "calendar.nope"}).content.startswith("bad_arguments")
    assert house.done == []


@pytest.mark.parametrize("arguments", [{"from": "tomorrow"}, {"from": "2026-13-45"}, {"days": 0}, {"days": 99},
                                       {"days": True}, {"calendar": ""}])
def test_bad_arguments_ask_the_house_nothing(house: MemoryHouse, arguments: dict[str, object]) -> None:
    assert call(arguments).content.startswith("bad_arguments")
    assert house.done == []


@pytest.mark.parametrize("fault", ["down", "refused", "malformed"])
def test_a_house_that_cannot_say_is_unread_not_empty(house: MemoryHouse, fault: str) -> None:
    house.refuse = "no" if fault == "refused" else None
    if fault == "malformed":
        house.returns["calendar.get_events"] = {FAMILY: {"events": "soon"}, SCHOOL: {"events": []}}
    house.down = fault == "down"
    got = body(call())
    assert got["unread"] == [NAME] and got["events"] == []


def test_a_port_switched_off_is_as_if_the_connection_did_not_serve_calendars(house: MemoryHouse) -> None:
    services.register(SettingsReader, Switches({}, frozenset({"calendar"})))
    assert asyncio.run(tools().catalogue()).specs == ()
    assert call().content.startswith("not_connected")
    assert house.done == []


def test_a_connections_link_that_cannot_be_read_is_unavailable(house: MemoryHouse) -> None:
    held = HeldConnections()
    held.down = True
    services.register(Connections, held)
    assert call().content.startswith("unavailable")


def test_the_tool_is_offered_to_a_known_speaker_in_any_chat(house: MemoryHouse) -> None:
    satellite = Inbound(household_id=HOME.id, thread="device:7", text="what is on?", kind="command", medium="spoken",
                        audience="present", speaker_id=1, shared=True, place="kitchen", channel="voice", heard_as=1)
    assert "calendar" in sources(satellite)

