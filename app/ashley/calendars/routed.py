"""The Calendars port wired: every connection serving `calendar` (`ashley.connections.ports.opened_all`, which honours
the household's switches) is read by the adapter of its kind, and what they hold is combined, each calendar labelled
with its source. A connection of a kind with no adapter is skipped; a source that fails is `unread`, so one service
being down never hides the others, nor reads as an empty calendar."""

import logging
import time
from collections.abc import Mapping
from datetime import datetime

from .. import logs, services
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened
from .calendars import Calendars
from .model import Agenda, Calendar, CalendarsFailed, CalendarsUnavailable, Event, NotConnected
from .source import CalendarSource

log = logging.getLogger("ashley.calendars")


class RoutedCalendars(Calendars):
    def __init__(self, adapters: Mapping[str, CalendarSource]) -> None:
        self._adapters = dict(adapters)

    async def _serving(self, household_id: int) -> list[Opened]:
        try:
            found = await ports.opened_all(services.get(Connections), "calendar", household_id)
        except ConnectionsUnavailable as e:
            raise CalendarsUnavailable from e
        return [o for o in found if o.connection.kind in self._adapters]

    async def connected(self, household_id: int) -> bool:
        return bool(await self._serving(household_id))

    async def agenda(self, household_id: int, start: datetime, end: datetime,
                     only: tuple[str, ...] | None = None) -> Agenda:
        began = time.monotonic()
        serving = await self._serving(household_id)
        if not serving:
            raise NotConnected
        calendars: list[Calendar] = []
        events: list[Event] = []
        unread: list[str] = []
        for opened in serving:
            kind = opened.connection.kind
            try:
                found = await self._adapters[kind].calendars(opened)
                chosen = tuple(c for c in found if only is None or c.id in only)
                events.extend(await self._adapters[kind].events(opened, chosen, start, end) if chosen else ())
            except CalendarsFailed as e:
                logs.warning(log, "calendar.unread", source=kind, connection=opened.connection.id, reason=e.reason)
                unread.append(kind)
                continue
            calendars.extend(chosen)
        logs.info(log, "calendar.read", sources=len(serving), calendars=len(calendars), events=len(events),
                  unread=len(unread), duration_ms=int((time.monotonic() - began) * 1000))
        return Agenda(tuple(calendars), tuple(events), tuple(unread))
