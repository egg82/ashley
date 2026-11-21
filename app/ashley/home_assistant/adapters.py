"""Home Assistant's adapters registered behind the neutral ports it serves (`ashley.wiring` calls `register`)."""

from .. import services
from ..calendars.calendars import Calendars
from ..calendars.routed import RoutedCalendars
from ..cameras.cameras import Cameras
from ..cameras.routed import RoutedCameras
from ..todos.routed import RoutedTodos
from ..todos.todos import Todos
from . import calendars, cameras, todos


def register(max_recordings: int) -> None:
    """`max_recordings`: the most of a camera's recordings she is listed (`ashley.looks.config`)."""
    services.register(Calendars, RoutedCalendars({calendars.NAME: calendars.HaCalendars()}))
    services.register(Cameras, RoutedCameras({cameras.NAME: cameras.HaCameras()}, max_recordings))
    services.register(Todos, RoutedTodos({todos.NAME: todos.HaTodos()}))
