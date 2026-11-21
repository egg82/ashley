"""Calendar from each household's own Home Assistant (`ashley.home_assistant.homes.Homes`): `calendar.get_events`
over the calendars the household listed in its `glance_calendars` setting, run through the house as `house_ask` runs a
read, and read by the Calendars port's Home Assistant adapter's own parser. A household that switched its Home Assistant's
`calendar` port off has none."""

import logging
import time
from datetime import datetime
from typing import Literal

from .. import logs, services
from ..home_assistant import house_values
from ..home_assistant.calendars import ACTION, parse
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseRejected, HouseUnavailable
from .calendar import Calendar, CalendarEvent, CalendarRead

log = logging.getLogger("ashley.senses")


class HomesCalendar(Calendar):
    async def events(self, household_id: int, start: datetime, end: datetime) -> CalendarRead:
        began = time.monotonic()
        try:
            home = await services.get(Homes).of(household_id)
            if home is None or not await services.get(Homes).reads_calendars(household_id):
                return "not_connected"
        except HomesUnavailable:
            return _unknown("house_unavailable", began)
        calendars = (await house_values.read(household_id)).glance_calendars
        if not calendars:
            return "not_connected"
        try:
            done = await home.house.perform(ACTION, calendars, {"start_date_time": start.isoformat(),
                                                                "end_date_time": end.isoformat()})
        except HouseRejected:
            return _unknown("refused", began)
        except HouseUnavailable:
            return _unknown("unreachable", began)
        found = parse(done.response, calendars)
        if found is None:
            return _unknown("malformed", began)
        logs.info(log, "calendar.read", events=len(found), duration_ms=int((time.monotonic() - began) * 1000))
        return tuple(CalendarEvent(e.title, e.start) for e in found)


def _unknown(reason: str, began: float) -> Literal["unknown"]:
    logs.warning(log, "calendar.unknown", reason=reason, duration_ms=int((time.monotonic() - began) * 1000))
    return "unknown"
