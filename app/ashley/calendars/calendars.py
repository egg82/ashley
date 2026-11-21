"""The Calendars service (`ashley.services`): a household's calendars and their events as neutral records (`model`),
from every connection that serves the `calendar` port and that the household has not switched off, labelled with its
source. It only reads. Callers import this module and `model`; adapters implement `source.CalendarSource`."""

from abc import abstractmethod
from datetime import datetime

from ..services import Service
from .model import Agenda, NotConnected


class Calendars(Service):
    @classmethod
    def null(cls) -> "Calendars":
        return NullCalendars()

    @abstractmethod
    async def connected(self, household_id: int) -> bool:
        """Whether any of the household's connections serves calendars now. Raises CalendarsUnavailable."""

    @abstractmethod
    async def agenda(self, household_id: int, start: datetime, end: datetime,
                     only: tuple[str, ...] | None = None) -> Agenda:
        """The calendars of every serving connection (those whose id is in `only` when given) and their events that
        start in [`start`, `end`), both aware. A source that fails is named in `Agenda.unread`, not raised. Raises
        NotConnected, CalendarsUnavailable. Logs `calendar.read` with counts and duration_ms, never a title."""


class NullCalendars(Calendars):
    """No household has a calendar source."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def agenda(self, household_id: int, start: datetime, end: datetime,
                     only: tuple[str, ...] | None = None) -> Agenda:
        raise NotConnected
