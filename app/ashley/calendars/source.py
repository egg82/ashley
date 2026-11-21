"""One service's calendars, behind the Calendars port: the adapter contract. An adapter reads only; the router
(`ashley.calendars.routed`) chooses which connections are asked."""

from abc import ABC, abstractmethod
from datetime import datetime

from ..connections.model import Opened
from .model import Calendar, Event


class CalendarSource(ABC):
    @abstractmethod
    async def calendars(self, opened: Opened) -> tuple[Calendar, ...]:
        """The calendars the connection reaches. Raises CalendarsFailed."""

    @abstractmethod
    async def events(self, opened: Opened, calendars: tuple[Calendar, ...], start: datetime,
                     end: datetime) -> tuple[Event, ...]:
        """The events of `calendars` (as `calendars` listed them) that start in [`start`, `end`), both aware, in no
        particular order. Raises CalendarsFailed."""
