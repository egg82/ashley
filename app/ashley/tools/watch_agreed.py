"""Arming one watch and telling the model what it did: the result of `watch` for a target read now, and of
`arm_reminder` agreeing a watch she proposed. Arguments and results are never logged; `tools.call` carries the outcome
and the watch id."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import services
from ..inference.model import ToolCall, ToolResult
from ..people.people import People, PeopleUnavailable
from ..senses.proposal_payloads import WatchSchedule
from ..senses.repeat import LOCAL_FORMAT
from ..watches import arming
from ..watches.arming import Ask, Seen
from ..watches.model import FailReason, ReadFailed
from ..watches.registry import KINDS
from ..watches.watches import WatchesUnavailable
from . import bench_results, watch_conditions
from .bench_args import BadArguments
from .tools import ToolsUnavailable

HINTS: dict[FailReason, str] = {
    "unreachable": "its source did not answer; tell the person it cannot be reached just now",
    "not_connected": "the person has not connected the source this kind reads",
    "refused": "the source turned the person's connection away; they can set it up again in settings",
    "bad_result": "the source answered with something unexpected",
    "too_many_items": "that reads too many items to keep watch on",
    "unknown_kind": "no such kind of watch"}
NOT_FOUND = "the source does not list that target; read its list again and use the id as listed"


async def zone_of(household_id: int) -> ZoneInfo:
    """The household's zone. Raises ToolsUnavailable."""
    try:
        household = await services.get(People).household(household_id)
    except PeopleUnavailable as e:
        raise ToolsUnavailable("people unavailable") from e
    if household is None:
        raise ToolsUnavailable("no such household")
    return ZoneInfo(household.timezone)


def local(moment: datetime, zone: ZoneInfo) -> str:
    return moment.astimezone(zone).strftime(LOCAL_FORMAT)


async def read(call: ToolCall, started: float, ask: Ask, now: datetime) -> Seen | ToolResult:
    """The target read once, or the error result for a read that failed or a target that is not there."""
    seen = await arming.look(ask.household_id, ask.person_id, ask.kind, ask.target, now)
    if isinstance(seen, ReadFailed):
        return bench_results.failed(call, started, seen.reason, HINTS[seen.reason])
    if seen is None:
        return bench_results.failed(call, started, "not_found", NOT_FOUND)
    return seen


async def arm(call: ToolCall, started: float, ask: Ask) -> ToolResult:
    """Read the target once and, if it is there, store the watch with that read as its baseline; the result is outside
    text when the kind says what it reads can be. Raises BadArguments for what the store refuses, ToolsUnavailable."""
    zone, now = await zone_of(ask.household_id), datetime.now(UTC)
    seen = await read(call, started, ask, now)
    if isinstance(seen, ToolResult):
        return seen
    try:
        armed = await arming.start(ask, seen, now)
    except ValueError as e:
        raise BadArguments(str(e)) from e
    except WatchesUnavailable as e:
        raise ToolsUnavailable("watches unavailable") from e
    return bench_results.ok(call, started, _body(ask, seen, now, zone, armed.new), outside=KINDS.get(ask.kind).outside,
                            watch=armed.id, new=armed.new)


async def arm_agreed(call: ToolCall, started: float, schedule: WatchSchedule) -> ToolResult:
    """The watch she proposed, armed now that the person agreed."""
    r = schedule.reminder
    ask = Ask(r.household_id, r.person_id, schedule.bench_id, schedule.kind, schedule.target, schedule.until, r.tools,
              schedule.hours, schedule.brief, schedule.standing, r.taint, r.made_in)
    return await arm(call, started, ask)


def _body(ask: Ask, seen: Seen, now: datetime, zone: ZoneInfo, new: bool) -> dict[str, object]:
    ends = now + timedelta(hours=arming.hours_of(ask.kind, ask.hours))
    return {"armed": True, "new": new, "standing": ask.standing, "label": seen.label, "now": {i: dict(f) for i, f in seen.items.items()},
            "until": None if ask.until is None else watch_conditions.say(ask.until), "ends": local(ends, zone)}
