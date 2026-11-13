"""The Calendar service (`ashley.services`): what is on the household's shared calendars between two moments, for the
screens that show it. The first implementation reads Home Assistant (`homes_calendar.HomesCalendar`), over the calendars
the household's Home Assistant connection lists in its `glance_calendars` setting.

Event titles are people's data and invite text: logs carry counts, never a title."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from ..services import Service


@dataclass(frozen=True)
class CalendarEvent:
    """`start` is a moment for a timed event and a date for an all-day one."""

    title: str
    start: date | datetime


CalendarRead = tuple[CalendarEvent, ...] | Literal["not_connected", "unknown"]
"""The events in no particular order; `not_connected` when the household has no house or has listed no calendar,
`unknown` when they could not be read now."""


class Calendar(Service):
    @classmethod
    def null(cls) -> "Calendar":
        return NullCalendar()

    @abstractmethod
    async def events(self, household_id: int, start: datetime, end: datetime) -> CalendarRead:
        """The events of the household's listed calendars that start in [`start`, `end`), `start` and `end` aware.
        Never raises. Logs `calendar.read` with the event count and duration_ms, or `calendar.unknown` with the
        reason."""


class NullCalendar(Calendar):
    """What an unwired process sees: no calendar is connected."""

    async def events(self, household_id: int, start: datetime, end: datetime) -> CalendarRead:
        return "not_connected"
