"""`house_history`: how things in the house changed over time, from the house's own record: each named thing's states
over the last hours (`history`), or the house's logbook of what happened (`logbook`). The things are named as every
house tool names them (`ids`, or `area`, `domain` and `name` as `house_state` matches them). Times are given as minutes
ago, so she reads them against now.

The `tools.call` line carries the kind, how many things, and how many readings or entries."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from ..home_assistant.house import House, LogEntry, Series, Window
from ..inference.model import ToolSpec
from . import house_args as args
from .house_answer import Answer, error, fit
from .house_look_config import HouseLookConfig
from .house_query import Query
from .house_targets import entity_of, resolve

NAME = "house_history"
DESCRIPTION = (
    "How things in the house changed over time, from the house's own record. kind history (default): the states of the "
    "things you name over the last hours, each change with how many minutes ago. kind logbook: what happened in the "
    "house (things turning on and off, automations running, people arriving), for the things you name or, naming none, "
    "the whole house. Name things by ids, or by name, area and domain as house_state takes them. hours says how far "
    "back; times are minutes ago.")
PARAMETERS = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["history", "logbook"]},
    "ids": {"type": "array", "items": {"type": "string"}, "description": "Exact ids, as an answer showed them."},
    "name": {"type": "string", "description": "Words from the thing's name."},
    "area": {"type": "string"}, "domain": {"type": "string"},
    "hours": {"type": "integer", "description": "How many hours back; the default is a day."}}}
SPEC = ToolSpec(NAME, DESCRIPTION, PARAMETERS, reads=True, outside=False)
_ARGUMENTS = ("kind", "ids", "name", "area", "domain", "hours")


async def run(house: House, arguments: Mapping[str, object], config: HouseLookConfig) -> Answer:
    args.only(arguments, NAME, _ARGUMENTS)
    kind = args.text(arguments, "kind") or "history"
    if kind not in ("history", "logbook"):
        raise ValueError("kind is history or logbook")
    hours = args.number(arguments, "hours", config.history_default_hours, config.history_max_hours)
    query = Query(args.text(arguments, "area"), args.text(arguments, "domain"), args.text(arguments, "name"))
    named = args.texts(arguments, "ids")
    if not named and query.given() == ():
        if kind == "history":
            return error("name the things: ids, or name, area and domain")
        targets: tuple[str, ...] = ()
    else:
        found = resolve(tuple(entity_of(s) for s in await house.states()), query, named)
        if not found.ids:
            return error("nothing in the house matches that" if not found.ambiguous
                         else f"that fits several: {', '.join(found.ambiguous)}; name one")
        targets = found.ids
    limit = config.history_max_things if kind == "history" else config.logbook_max_things
    if len(targets) > limit:
        return error(f"that is {len(targets)} things; name at most {limit}", things=len(targets))
    now = datetime.now(UTC)
    window = Window(now - timedelta(hours=hours), now, targets)
    if kind == "history":
        return _history(await house.history(window), now, hours, config)
    return _logbook(await house.logbook(window), now, hours, config)


def _history(series: tuple[Series, ...], now: datetime, hours: int, config: HouseLookConfig) -> Answer:
    things = [{"id": s.id, "changes": len(s.readings), "readings": _readings(s, now, config)} for s in series]
    complete = all(len(s.readings) <= config.readings_per_thing for s in series)
    body = {"kind": "history", "hours": hours, "complete": complete, "things": things,
            **({} if complete else {"note": f"only the latest {config.readings_per_thing} changes of each are shown"})}
    text, form = fit([body, {"kind": "history", "hours": hours, "complete": False, "narrow_by": ["hours", "ids"],
                             "things": [{"id": t["id"], "changes": t["changes"]} for t in things]}], config.max_chars)
    return Answer(text, False, {"kind": "history", "things": len(things), "readings": sum(s.readings.__len__() for s in series),
                                "form": form})


def _readings(series: Series, now: datetime, config: HouseLookConfig) -> list[dict[str, object]]:
    latest = series.readings[-config.readings_per_thing:]
    return [{"ago_min": max(0, int((now - r.at).total_seconds() // 60)), "state": r.state} for r in latest]


def _logbook(entries: tuple[LogEntry, ...], now: datetime, hours: int, config: HouseLookConfig) -> Answer:
    latest = entries[-config.entries_max:]
    body = {"kind": "logbook", "hours": hours, "total": len(entries), "complete": len(latest) == len(entries),
            "entries": [{"ago_min": max(0, int((now - e.at).total_seconds() // 60)), "name": e.name,
                         "what": e.message} for e in latest]}
    text, form = fit([body, {"kind": "logbook", "hours": hours, "total": len(entries), "complete": False,
                             "narrow_by": ["hours", "ids"]}], config.max_chars)
    return Answer(text, False, {"kind": "logbook", "entries": len(entries), "form": form})
