"""A reminder's schedule, delivery and tools as her tools receive them (`reminders.ReminderTools`): the fields she sets,
turned into a `Repeat`, a first time, a route and a tool list, or refused with `BadArguments`. Times are the
household's wall clock."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from ..inference.model import ToolSpec
from ..senses.repeat import MAX_COUNT, MAX_EVERY, NTHS, Repeat, freq_of, instant, next_after, starts, until_after
from ..senses.wakes import MAX_TOOLS, ROUTES, Route
from .bench_args import BadArguments

ONCE = "none"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
REPEAT_KEYS = ("repeat", "every", "weekdays", "nth", "until", "count")
"""The arguments that shape how a reminder comes round; none given leaves the rule as it is."""

PROPERTIES: dict[str, dict[str, object]] = {
    "repeat": {"type": "string", "enum": [ONCE, "daily", "weekly", "monthly", "yearly"],
               "description": "how it comes round again from `at`; none for once"},
    "every": {"type": "integer", "minimum": 1, "maximum": MAX_EVERY,
              "description": "with repeat, every this many days/weeks/months/years; 1 if left out"},
    "weekdays": {"type": "array", "items": {"type": "string", "enum": list(DAYS)}, "minItems": 1, "maxItems": 7,
                 "description": "with weekly (or monthly and nth), only on these days; every weekday is "
                                "weekly with mon to fri. The first time is the first of these days on or after `at`"},
    "nth": {"type": "integer", "enum": list(NTHS),
            "description": "with monthly and weekdays, which one of the month: 1 to 4, or -1 for the last "
                           "(the first Monday of the month is monthly, mon, 1)"},
    "until": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$",
              "description": "the last day it may fall on, YYYY-MM-DD; give this or count, not both"},
    "count": {"type": "integer", "minimum": 1, "maximum": MAX_COUNT,
              "description": "stop after this many times (for the next six weeks of Sundays: 6)"},
}
DELIVERY: dict[str, object] = {"type": "string", "enum": list(ROUTES),
            "description": "phone to push what you say to their phone (the default); quiet to say nothing to "
                           "them, for a reminder that only does something; room to say it aloud through a satellite, "
                           "or screen to show it on a shared screen, either named by device (its phone if not "
                           "reached there)"}
DEVICE: dict[str, object] = {"type": "integer",
          "description": "with room or screen, the id of the device from household_devices: a satellite for room, a "
                         "screen for screen"}
TOOLS: dict[str, object] = {"type": "array", "items": {"type": "string"}, "maxItems": MAX_TOOLS,
         "description": "the names of tools that its turn may use when it falls due, from the tools you have now; "
                        "without it only tools that look, never ones that act. The person must agree to ones that act"}


def repeat_of(args: Mapping[str, object], anchor: datetime, base: Repeat | None) -> Repeat | None:
    """The rule the arguments describe, starting at `anchor`: with none of `REPEAT_KEYS`, `base` moved to `anchor`; with
    `repeat`, a new rule from the arguments alone; with others only, `base` changed by them. None for once."""
    if not any(k in args for k in REPEAT_KEYS):
        return None if base is None else _made(lambda: replace(base, anchor=anchor))
    if args.get("repeat") == ONCE:
        return None
    fresh = "repeat" in args
    freq = freq_of(args["repeat"]) if fresh else None if base is None else base.freq
    if freq is None:
        raise BadArguments("repeat is none, daily, weekly, monthly or yearly")
    keep = None if fresh or base is None else base
    every = _int(args.get("every", 1 if keep is None else keep.every), "every")
    weekdays = _days(args["weekdays"]) if "weekdays" in args else () if keep is None else keep.weekdays
    nth = _int(args["nth"], "nth") if "nth" in args else None if keep is None else keep.nth
    until = _day(args["until"]) if "until" in args else None if keep is None else keep.until
    if "count" in args:
        if until is not None and "until" in args:
            raise BadArguments("give until or count, not both")
        until = _made(lambda: until_after(Repeat(freq, every, anchor, weekdays, nth), _int(args["count"], "count")))
    return _made(lambda: Repeat(freq, every, anchor, weekdays, nth, until))


def first_due(repeat: Repeat | None, local: datetime, zone: ZoneInfo, now: datetime) -> datetime:
    """When it first falls due: `local` for a one-off, which must be ahead; for a rule its first occurrence, or when
    that has passed the next one after `now`."""
    if repeat is None:
        due = instant(local, zone)
        if due <= now:
            raise BadArguments("that time has passed")
        return due
    first = starts(repeat)
    if first is None:
        raise BadArguments("it would end before it starts")
    due = instant(first, zone)
    if due > now:
        return due
    later = next_after(repeat, now, zone)
    if later is None:
        raise BadArguments("it has already ended")
    return later


def route_of(raw: object, default: Route) -> Route:
    """`raw` as a route; `default` when she left it out."""
    if raw is None:
        return default
    for route in ROUTES:
        if raw == route:
            return route
    raise BadArguments("delivery is phone, quiet, room or screen")


def tools_of(raw: object, usable: Mapping[str, ToolSpec]) -> tuple[str, ...] | None:
    """The tool names she gave, each one the person can use now (`usable`, by name); None for none given."""
    if raw is None:
        return None
    given = _strings(raw)
    if given is None:
        raise BadArguments("tools is a list of tool names")
    names = tuple(dict.fromkeys(given))
    if len(names) > MAX_TOOLS or any(n not in usable for n in names):
        raise BadArguments("tools are names of tools you have now, at most %d" % MAX_TOOLS)
    return names or None


def acts(names: tuple[str, ...] | None, usable: Mapping[str, ToolSpec]) -> bool:
    """Whether any of `names` changes something."""
    return names is not None and any(not usable[n].reads for n in names)


def _made[T](build: Callable[[], T]) -> T:
    """What `build` makes; a rule the repeat refuses is a bad argument."""
    try:
        return build()
    except ValueError as e:
        raise BadArguments(str(e)) from e


def _int(raw: object, name: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise BadArguments(f"{name} is an integer")
    return raw


def _days(raw: object) -> tuple[int, ...]:
    given = _strings(raw)
    if given is None or not all(d in DAYS for d in given):
        raise BadArguments("weekdays are from " + ", ".join(DAYS))
    return tuple(sorted({DAYS.index(d) for d in given}))


def _strings(raw: object) -> tuple[str, ...] | None:
    loose: Any = raw
    if not isinstance(raw, list):
        return None
    items = list[object](loose)
    return tuple(t for t in items if isinstance(t, str)) if all(isinstance(t, str) for t in items) else None


def _day(raw: object) -> date:
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) and len(raw) == len("YYYY-MM-DD") else _no_day()
    except ValueError:
        return _no_day()


def _no_day() -> NoReturn:
    raise BadArguments("until is a date as YYYY-MM-DD")
