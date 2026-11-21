"""Home Assistant's adapters registered behind the neutral ports it serves (`ashley.wiring` calls `register`)."""

from .. import services
from ..calendars.calendars import Calendars
from ..calendars.routed import RoutedCalendars
from ..todos.routed import RoutedTodos
from ..todos.todos import Todos
from . import calendars, todos


def register() -> None:
    services.register(Calendars, RoutedCalendars({calendars.NAME: calendars.HaCalendars()}))
    services.register(Todos, RoutedTodos({todos.NAME: todos.HaTodos()}))
