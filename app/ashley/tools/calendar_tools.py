"""The household's calendars, read through the Calendars port (`ashley.calendars.calendars`) as her `calendar_events`
tool (`calendar_specs`). Offered per turn by `ashley.channels.turn_tools.sources` to a known speaker, in any chat, as the
house's own reads are: a calendar the household marked `discreet` is answered about only when asked, which the tool's
instructions say. It only reads, so it is never held for an OK. A household with no calendar source is offered none. Tool
arguments and results are never logged; `tools.call` carries the tool, outcome and row count."""

import time
from collections.abc import Callable
from datetime import UTC, datetime, time as at, timedelta
from zoneinfo import ZoneInfo

from .. import services
from ..calendars.calendars import Calendars
from ..calendars.model import CalendarsUnavailable, NotConnected
from ..inference.model import ToolCall, ToolResult
from ..people.people import People, PeopleUnavailable
from . import bench_results, calendar_render
from .calendar_config import CalendarConfig
from .calendar_specs import EVENTS, INSTRUCTIONS, events_query, spec
from .tools import Catalogue, Tools, ToolsUnavailable

_UNAVAILABLE = "the household's connections cannot be read"
_NOT_CONNECTED = "the household has no calendar connected, or has switched calendars off"


class CalendarTools(Tools):
    def __init__(self, household_id: int, config: CalendarConfig,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._household_id = household_id
        self._config = config
        self._now = now

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no calendar source. Raises ToolsUnavailable when its link cannot be read."""
        try:
            served = await services.get(Calendars).connected(self._household_id)
        except CalendarsUnavailable as e:
            raise ToolsUnavailable("calendars unavailable") from e
        return Catalogue((spec(self._config),), INSTRUCTIONS) if served else Catalogue((), None)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no source, or a source failing are each an error result."""
        started = time.monotonic()
        if call.name != EVENTS:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        query = events_query(dict(call.arguments), self._config)
        if isinstance(query, str):
            return bench_results.failed(call, started, "bad_arguments", query)
        try:
            zone = await self._zone()
            first = query.first or self._now().astimezone(zone).date()
            start = datetime.combine(first, at.min, zone)
            end = datetime.combine(first + timedelta(days=query.days), at.min, zone)
            only = None if query.calendar is None else (query.calendar,)
            found = await services.get(Calendars).agenda(self._household_id, start, end, only)
        except (ToolsUnavailable, CalendarsUnavailable):
            return bench_results.failed(call, started, "unavailable", _UNAVAILABLE)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", _NOT_CONNECTED)
        if query.calendar is not None and not found.calendars and not found.unread:
            return bench_results.failed(call, started, "bad_arguments",
                                        "calendar is not a calendar of the household; calendar_events lists them")
        shown = calendar_render.agenda(found, zone, self._config.events_max)
        return bench_results.ok(call, started, shown, rows=len(found.events))

    async def _zone(self) -> ZoneInfo:
        try:
            household = await services.get(People).household(self._household_id)
        except PeopleUnavailable as e:
            raise ToolsUnavailable("people unavailable") from e
        if household is None:
            raise ToolsUnavailable("no such household")
        return ZoneInfo(household.timezone)
