"""A household's calendars as she sees them, whichever service holds them: plain records whose fields are stated in
calendar terms. An adapter (for Home Assistant, `ashley.home_assistant.calendars`) fills them from its service's own
shapes; nothing outside it knows those shapes."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from ..hearing import Visibility

Reason = Literal["refused", "unreachable", "unrecognised"]
"""Why a read failed: `refused`, the service turned the household's credentials away; `unreachable`, no answer in time
or a server error; `unrecognised`, the answer is not the service's own shape."""


@dataclass(frozen=True)
class Calendar:
    """One calendar: `id` is the service's own, `title` what it is called there, `source` the kind of connection that
    holds it and `connection_id` which one. `visibility` is how freely she may speak of its events
    (`ashley.hearing.Visibility`): `shared`, or `discreet` for one the household marked so."""

    id: str
    title: str
    source: str
    connection_id: int
    visibility: Visibility


@dataclass(frozen=True)
class Event:
    """One event of the calendar `calendar_id`. A timed event's `start` and `end` are moments, aware when the service
    gave an offset; an all-day event (`all_day`) has dates, `end` the day it ends on as the service says it. `end` and
    `location` are None when the service gives none. `title` and `location` can be written by whoever sent an invite."""

    title: str
    start: date | datetime
    end: date | datetime | None
    all_day: bool
    location: str | None
    calendar_id: str


@dataclass(frozen=True)
class Agenda:
    """What the household's calendars hold in a window: the `calendars` read, their `events` in no particular order,
    and the `unread` sources (connection kinds) that could not be read now, whose calendars and events are missing."""

    calendars: tuple[Calendar, ...]
    events: tuple[Event, ...]
    unread: tuple[str, ...]


class CalendarsFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class CalendarsUnavailable(Exception):
    """The household's connections cannot be read now."""


class NotConnected(Exception):
    """The household has no calendar source switched on."""
