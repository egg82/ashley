"""Home Assistant's calendars behind the Calendars port: the household's `calendar` entities (`House.states`) and
`calendar.get_events` run through the house as `house_ask` runs a read, over the one client `Homes` keeps. Only here are
its field names read. The `discreet_calendars` setting marks the calendars whose events she does not volunteer."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from .. import services
from ..calendars.model import Calendar, CalendarsFailed, Event
from ..calendars.source import CalendarSource
from ..connections.model import Opened
from . import house_values
from .ha_json import JsonObject, is_list, obj, rows
from .homes import Homes, HomesUnavailable
from .house import House, HouseRejected, HouseUnavailable

NAME = "home_assistant"
ACTION = "calendar.get_events"
TEXT_CHARS = 120


async def _house(opened: Opened) -> House | None:
    try:
        home = await services.get(Homes).of(opened.connection.household_id)
    except HomesUnavailable as e:
        raise CalendarsFailed("unreachable") from e
    return None if home is None else home.house


class HaCalendars(CalendarSource):
    async def calendars(self, opened: Opened) -> tuple[Calendar, ...]:
        house = await _house(opened)
        if house is None:
            return ()
        try:
            states = await house.states()
        except HouseUnavailable as e:
            raise CalendarsFailed("unreachable") from e
        discreet = (await house_values.read(opened.connection.household_id)).discreet_calendars
        return tuple(Calendar(s.id, s.name, NAME, opened.connection.id, "discreet" if s.id in discreet else "shared")
                     for s in states if s.domain == "calendar")

    async def events(self, opened: Opened, calendars: tuple[Calendar, ...], start: datetime,
                     end: datetime) -> tuple[Event, ...]:
        house = await _house(opened)
        if house is None:
            return ()
        ids = tuple(c.id for c in calendars)
        try:
            done = await house.perform(ACTION, ids, {"start_date_time": start.isoformat(),
                                                     "end_date_time": end.isoformat()})
        except HouseRejected as e:
            raise CalendarsFailed("refused") from e
        except HouseUnavailable as e:
            raise CalendarsFailed("unreachable") from e
        found = parse(done.response, ids)
        if found is None:
            raise CalendarsFailed("unrecognised")
        return tuple(found)


def parse(response: Mapping[str, Any] | None, calendars: tuple[str, ...]) -> list[Event] | None:
    """The events of `calendars` in a `calendar.get_events` response; None when it is not that shape."""
    if response is None:
        return None
    out: list[Event] = []
    for calendar in calendars:
        held = obj(response.get(calendar)).get("events")
        if not is_list(held):
            return None
        for row in rows(held):
            event = _event(row, calendar)
            if event is None:
                return None
            out.append(event)
    return out


def moment(value: object) -> date | datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
    except ValueError:
        return None


def _text(value: object) -> str | None:
    return value.strip()[:TEXT_CHARS] or None if isinstance(value, str) else None


def _event(row: JsonObject, calendar: str) -> Event | None:
    title, start = row.get("summary"), moment(row.get("start"))
    if not isinstance(title, str) or start is None:
        return None
    return Event(title.strip()[:TEXT_CHARS], start, moment(row.get("end")), not isinstance(start, datetime),
                 _text(row.get("location")), calendar)
