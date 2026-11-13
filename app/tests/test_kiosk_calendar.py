"""The kiosk glance's calendar: today's and tomorrow's events of the calendars the household listed, read through the
household's house (`senses.homes_calendar.HomesCalendar`), on the household's own day, title and time only; not
connected until a calendar is listed, unknown when the house cannot say, and never a title in a log."""

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from ashley import logs, services
from ashley.channels.kiosk.glance import Glance, GlanceEvent, glance
from ashley.connections.model import Port
from ashley.connections.settings import SettingValues
from ashley.connections.settings_read import Change, SettingsReader, StoredSettings
from ashley.home_assistant.homes import Homes
from ashley.people.people import People
from ashley.senses.calendar import Calendar
from ashley.senses.homes_calendar import HomesCalendar
from ashley.senses.presence import Presence
from ashley.services import Service
from homes_support import AnyHousehold
from house_double_support import MemoryHouse
from respond_support import HOME, FakePeople, FakePresence

NOW = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)
LISTED = ("calendar.zq_family", "calendar.zq_school")
_SERVICES: tuple[type[Service], ...] = (Homes, SettingsReader, Calendar, People, Presence)


class Listed(SettingsReader):
    def __init__(self, values: SettingValues) -> None:
        self.values = values

    async def of(self, household_id: int, port: Port) -> SettingValues:
        return self.values

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        raise AssertionError("not read here")

    async def history(self, connection_id: int, household_id: int, limit: int,
                      before: int | None = None) -> tuple[Change, ...]:
        raise AssertionError("not read here")


def _event(summary: str, start: str) -> dict[str, str]:
    return {"summary": summary, "start": start, "end": start}


@pytest.fixture
def house() -> Generator[MemoryHouse]:
    made = MemoryHouse()
    made.returns["calendar.get_events"] = {
        "calendar.zq_family": {"events": [_event("Soccer", "2026-11-13T16:30:00-07:00"),
                                          _event("Dentist", "2026-11-14T05:00:00-07:00"),
                                          _event("Next week", "2026-11-15")]},
        "calendar.zq_school": {"events": [_event("Trash day", "2026-11-13"),
                                          _event("Late", "2026-11-14T03:00:00+00:00")]}}
    services.register(Homes, AnyHousehold(made))
    services.register(SettingsReader, Listed({"glance_calendars": list(LISTED)}))
    services.register(Calendar, HomesCalendar())
    services.register(People, FakePeople())
    services.register(Presence, FakePresence(frozenset()))
    yield made
    for interface in _SERVICES:
        services.unregister(interface)


def _glance() -> Glance:
    return asyncio.run(glance(HOME.id, lambda: NOW))


def test_the_glance_shows_today_and_tomorrow_on_the_households_day_in_order(house: MemoryHouse) -> None:
    assert _glance().calendar == (
        GlanceEvent("Trash day", "today", None), GlanceEvent("Soccer", "today", "16:30"),
        GlanceEvent("Late", "today", "20:00"), GlanceEvent("Dentist", "tomorrow", "05:00"))
    action, ids, data = house.done[0][2:]
    assert (action, ids) == ("calendar.get_events", LISTED)
    assert (data["start_date_time"], data["end_date_time"]) == ("2026-11-13T00:00:00-07:00", "2026-11-15T00:00:00-07:00")


def test_no_listed_calendar_is_not_connected_and_the_house_is_not_asked(house: MemoryHouse) -> None:
    services.register(SettingsReader, Listed({}))
    assert _glance().calendar == "not_connected"
    assert house.done == []


@pytest.mark.parametrize("fault", ["down", "refused", "malformed"])
def test_a_house_that_cannot_say_is_unknown_not_empty(house: MemoryHouse, fault: str) -> None:
    house.down = fault == "down"
    house.refuse = "no" if fault == "refused" else None
    if fault == "malformed":
        house.returns["calendar.get_events"] = {"calendar.zq_family": {"events": "soon"}}
    assert _glance().calendar == "unknown"


def test_a_quiet_day_is_an_empty_list_not_unknown(house: MemoryHouse) -> None:
    house.returns["calendar.get_events"] = {c: {"events": []} for c in LISTED}
    assert _glance().calendar == ()


def test_the_log_counts_events_and_never_names_one(house: MemoryHouse, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    _glance()
    out = capsys.readouterr().out
    assert "event=calendar.read events=5" in out
    assert all(title not in out for title in ("Soccer", "Dentist", "Trash"))


def test_at_most_a_handful_of_events_are_shown(house: MemoryHouse) -> None:
    house.returns["calendar.get_events"] = {
        "calendar.zq_family": {"events": [_event(f"E{i}", f"2026-11-13T{i + 8:02d}:00:00-07:00") for i in range(12)]},
        "calendar.zq_school": {"events": []}}
    shown = _glance().calendar
    assert len(shown) == 8 and shown[0].title == "E0"
