"""Arming a watch for a person who asked for it (`decisions.md`, "Watches wake her when what a read returns changes,
until a condition or a time"): read the target once through its kind, and store a watch with the kind's defaults and
that read as its baseline. Logs `watches.armed` (watch id, kind, person, `armed_by`, new, hours), never a target."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import logs, services
from ..criteria.condition import Condition
from .config import CONFIG
from .diff import Items
from .kinds import Registry
from .model import Arm, Armed, Later, ReadFailed, Watch
from .registry import KINDS
from .watches import Watches

log = logging.getLogger("ashley.watches")


@dataclass(frozen=True)
class Seen:
    """A target as its kind reads it now: what a person calls it, and its tracked fields."""

    label: str
    items: Items


def probe(household_id: int, person_id: int, kind: str, target: str, now: datetime) -> Watch:
    """A watch that is never stored, only handed to a kind to read `target` once."""
    return Watch(0, household_id, person_id, kind, target, target, None, "ashley", CONFIG.kinds[kind].track,
                 CONFIG.kinds[kind].when, None, None, CONFIG.kinds[kind].interval_s, now, "armed", None, 0, 0, 0, None,
                 now, now, None, None)


async def look(household_id: int, person_id: int, kind: str, target: str, now: datetime,
               kinds: Registry = KINDS) -> Seen | ReadFailed | None:
    """The target read once; None when the read succeeds with no items and the kind takes that as the target not there. A read that raises or outlasts
    `read_timeout_s`, and a source not ready yet (`Later`), is `ReadFailed` `unreachable`."""
    watch = probe(household_id, person_id, kind, target, now)
    source = kinds.get(kind)
    try:
        async with asyncio.timeout(CONFIG.read_timeout_s):
            got = (await source.read([watch]))[0]
            if isinstance(got, ReadFailed):
                return got
            if isinstance(got, Later):
                return ReadFailed("unreachable")
            return Seen(await source.label(watch), got) if got or not source.empty_is_absent else None
    except Exception:
        return ReadFailed("unreachable")


def hours_of(kind: str, hours: float | None) -> float:
    """`hours` or the kind's default. Raises ValueError for one outside 1 to the kind's `max_hours`."""
    config = CONFIG.kinds[kind]
    chosen = config.hours if hours is None else hours
    if not 1 <= chosen <= config.max_hours:
        raise ValueError(f"hours is 1 to {config.max_hours:g}")
    return chosen


@dataclass(frozen=True)
class Ask:
    """A person's request to watch `target` of `kind`, for `hours` (None: the kind's default), ending at `until`, its
    turn using `tools` (None: only the ones that read), on the talk of bench `bench_id` if any. `brief`, `standing`,
    `taint` and `made_in` are as `Arm` has them. `track` and `when` are the kind's own when None; `tool` gives them, its
    target saying which fields it tracks."""

    household_id: int
    person_id: int
    bench_id: int | None
    kind: str
    target: str
    until: Condition | None
    tools: tuple[str, ...] | None
    hours: float | None
    brief: str | None = None
    standing: bool = False
    taint: str | None = None
    made_in: tuple[int, int] | None = None
    track: tuple[str, ...] | None = None
    when: Condition | None = None


async def start(ask: Ask, seen: Seen | None, now: datetime) -> Armed:
    """Store the watch, with `seen` as its baseline (None: the first check baselines). Raises ValueError as
    `hours_of` and `Watches.arm` do, WatchesUnavailable."""
    config, chosen = CONFIG.kinds[ask.kind], hours_of(ask.kind, ask.hours)
    label = (seen.label if seen else ask.target)[:100] or ask.target[:100]
    arm = Arm(ask.household_id, ask.person_id, ask.kind, ask.target, label, ask.bench_id, "ashley",
              ask.track or config.track, ask.when or config.when, ask.until, ask.tools, config.interval_s,
              now + timedelta(hours=chosen), None if seen is None else seen.items, ask.brief, ask.standing, ask.taint,
              ask.made_in)
    armed = await services.get(Watches).arm(arm)
    logs.info(log, "watches.armed", watch=armed.id, kind=ask.kind, person=ask.person_id, armed_by="ashley",
              new=armed.new, hours=chosen)
    return armed
