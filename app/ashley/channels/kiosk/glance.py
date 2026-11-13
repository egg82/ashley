"""The hallway tablet's glance: who of the household is home, by first name, and how the household writes its clock.
Who is home is shown to whoever stands in the hallway, which is a house's own knowledge; nothing else about anyone is.
The calendar is today's and tomorrow's events of the calendars the household listed, title and time only, read on each
glance (the page reads on a timer) through `Calendar`; reminders have no source yet, so the route says so rather than
showing any.

Logs `kiosk.people_unavailable` when the household could not be read; who is home is never logged (Presence logs its
count), nor is an event's title (Calendar logs its count)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ... import logs, services
from ...people.model import Clock, Household
from ...people.people import People, PeopleUnavailable
from ...senses.calendar import Calendar, CalendarEvent
from ...senses.presence import Presence

log = logging.getLogger("ashley.channels.kiosk")


MAX_EVENTS = 8


@dataclass(frozen=True)
class GlanceEvent:
    """One event on the household's wall clock: `at` is `HH:MM`, None for an all-day event."""

    title: str
    day: Literal["today", "tomorrow"]
    at: str | None


Agenda = tuple[GlanceEvent, ...] | Literal["not_connected", "unknown"]


@dataclass(frozen=True)
class Glance:
    """`home` is the names of the household's people who are home, ordered by person id; empty when everyone known is
    away, None when it cannot be known (Presence answered unknown, or the household could not be read). `locale` and
    `clock` are the household's (`Household`), None when it could not be read. `calendar` is today's and tomorrow's
    events in order, at most `MAX_EVENTS`; `not_connected` when the household lists no calendar, `unknown` when they
    could not be read."""

    home: tuple[str, ...] | None
    locale: str | None
    clock: Clock | None
    calendar: Agenda = "unknown"


async def glance(household_id: int, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Glance:
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable:
        logs.warning(log, "kiosk.people_unavailable", household=household_id)
        return Glance(None, None, None)
    if household is None:
        return Glance(None, None, None)
    return Glance(await _home(household), household.locale, household.clock, await _agenda(household, now()))


async def _home(household: Household) -> tuple[str, ...] | None:
    present = await services.get(Presence).home(household.id)
    if present is None:
        return None
    return tuple(p.name for p in household.people if p.id in present)


async def _agenda(household: Household, now: datetime) -> Agenda:
    try:
        zone = ZoneInfo(household.timezone)
    except ZoneInfoNotFoundError:
        return "unknown"
    today = now.astimezone(zone).date()
    start = datetime.combine(today, time.min, zone)
    read = await services.get(Calendar).events(household.id, start, datetime.combine(today + timedelta(days=2), time.min, zone))
    if isinstance(read, str):
        return read
    shown = sorted((e for e in (_event(e, today, zone) for e in read) if e is not None), key=lambda e: e[0])
    return tuple(e[1] for e in shown[:MAX_EVENTS])


def _event(event: CalendarEvent, today: date, zone: ZoneInfo) -> tuple[tuple[date, bool, str], GlanceEvent] | None:
    start = event.start
    local = start.replace(tzinfo=zone) if isinstance(start, datetime) and start.tzinfo is None else start
    if isinstance(local, datetime):
        local = local.astimezone(zone)
    day = local.date() if isinstance(local, datetime) else local
    if day not in (today, today + timedelta(days=1)):
        return None
    at = local.strftime("%H:%M") if isinstance(local, datetime) else None
    seen = GlanceEvent(event.title, "today" if day == today else "tomorrow", at)
    return (day, at is not None, at or ""), seen
