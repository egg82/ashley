"""Home Assistant's adapters registered behind the neutral ports it serves (`ashley.wiring` calls `register`)."""

from .. import services
from ..calendars.calendars import Calendars
from ..calendars.routed import RoutedCalendars
from . import calendars


def register() -> None:
    services.register(Calendars, RoutedCalendars({calendars.NAME: calendars.HaCalendars()}))
