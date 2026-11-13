"""Calendar from each household's own Home Assistant (`ashley.home_assistant.homes.Homes`): `calendar.get_events`
over the calendars the household listed in its `glance_calendars` setting, run through the house as `house_ask` runs a
read."""

import logging
import time
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Literal

from .. import logs, services
from ..home_assistant.ha_json import JsonObject, is_list, obj, rows
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseRejected, HouseUnavailable
from ..home_assistant import house_values
from .calendar import Calendar, CalendarEvent, CalendarRead

log = logging.getLogger("ashley.senses")
ACTION = "calendar.get_events"
TITLE_CHARS = 120


class HomesCalendar(Calendar):
    async def events(self, household_id: int, start: datetime, end: datetime) -> CalendarRead:
        began = time.monotonic()
        try:
            home = await services.get(Homes).of(household_id)
        except HomesUnavailable:
            return _unknown("house_unavailable", began)
        calendars = (await house_values.read(household_id)).glance_calendars
        if home is None or not calendars:
            return "not_connected"
        try:
            done = await home.house.perform(ACTION, calendars, {"start_date_time": start.isoformat(),
                                                                "end_date_time": end.isoformat()})
        except HouseRejected:
            return _unknown("refused", began)
        except HouseUnavailable:
            return _unknown("unreachable", began)
        found = _events(done.response, calendars)
        if found is None:
            return _unknown("malformed", began)
        logs.info(log, "calendar.read", events=len(found), duration_ms=int((time.monotonic() - began) * 1000))
        return tuple(found)


def _events(response: Mapping[str, Any] | None, calendars: tuple[str, ...]) -> list[CalendarEvent] | None:
    if response is None:
        return None
    out: list[CalendarEvent] = []
    for calendar in calendars:
        held = obj(response.get(calendar)).get("events")
        if not is_list(held):
            return None
        for row in rows(held):
            event = _event(row)
            if event is None:
                return None
            out.append(event)
    return out


def _event(row: JsonObject) -> CalendarEvent | None:
    title, start = row.get("summary"), row.get("start")
    if not isinstance(title, str) or not isinstance(start, str):
        return None
    try:
        moment: date | datetime = datetime.fromisoformat(start) if "T" in start else date.fromisoformat(start)
    except ValueError:
        return None
    return CalendarEvent(title.strip()[:TITLE_CHARS], moment)


def _unknown(reason: str, began: float) -> Literal["unknown"]:
    logs.warning(log, "calendar.unknown", reason=reason, duration_ms=int((time.monotonic() - began) * 1000))
    return "unknown"
