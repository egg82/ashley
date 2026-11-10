"""The provider watch: every `interval_s`, under the lease `inference-watch`, read each watched task's calls of the last
`window_s` from the spend ledger and alert on any provider that failed at least `error_share` of at least `min_calls`
of them. A route list that falls through to the next provider hides one provider's outage from everything but this.

Tunables are data, `watch.json` beside this module. An alert is the warning `inference.provider_alert`; the watch
keeps no state, so it repeats on every evaluation while the share stays high and stops when it falls.

Logs `inference.watch` per evaluation (pairs seen, alerts raised, duration_ms), `inference.provider_alert` per
provider in breach (task, provider, calls, failed, share, window_s), and `inference.watch_unavailable` once per run of
evaluations that could not read the ledger. Ids, counts and durations only."""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from .. import logs, services
from ..db.database import Database, DatabaseUnavailable
from .model import Task
from .outcomes import Share, shares
from .provider import Failure

log = logging.getLogger("ashley.inference")
NAME = "inference-watch"
FILE = Path(__file__).with_name("watch.json")


@dataclass(frozen=True)
class WatchConfig:
    interval_s: float
    window_s: float
    min_calls: int
    error_share: float
    failing: tuple[str, ...]
    tasks: tuple[Task, ...]


def load() -> WatchConfig:
    """The tunables in `watch.json`. Raises ValueError for a missing or unknown key, a duration or count that is not
    positive, a share outside (0, 1], an outcome that is not a `Failure`, or a task that is not a text task."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> WatchConfig:
    raw = _object(data)
    if set(raw) != {"interval_s", "window_s", "min_calls", "error_share", "failing", "tasks"}:
        raise ValueError("watch config keys are interval_s, window_s, min_calls, error_share, failing, tasks")
    share = _number(raw["error_share"], "error_share")
    if not 0 < share <= 1:
        raise ValueError("error_share is above 0 and at most 1")
    min_calls = raw["min_calls"]
    if type(min_calls) is not int or min_calls < 1:
        raise ValueError("min_calls is a positive whole number")
    return WatchConfig(_number(raw["interval_s"], "interval_s"), _number(raw["window_s"], "window_s"), min_calls,
                       share, _names(raw["failing"], get_args(Failure), "failing"),
                       _names(raw["tasks"], get_args(Task), "tasks"))


def _object(data: object) -> dict[str, object]:
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("watch config is an object")
    return {str(k): v for k, v in dict[object, object](loose).items()}


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ValueError(f"{name} is a number above 0")
    return float(value)


def _names[T: str](value: object, allowed: tuple[T, ...], name: str) -> tuple[T, ...]:
    loose: Any = value
    items = list[object](loose) if isinstance(value, list) else []
    found = tuple(a for a in allowed if a in items)
    if not found or len(found) != len(items):
        raise ValueError(f"{name} is a non-empty list of names from {', '.join(allowed)}")
    return found


def breaches(seen: Iterable[Share], config: WatchConfig) -> list[Share]:
    """The pairs with at least `min_calls` calls whose failed share is at least `error_share`."""
    return [s for s in seen if s.calls >= config.min_calls and s.failed_share >= config.error_share]


async def evaluate(config: WatchConfig) -> list[Share]:
    """One evaluation: reads the ledger, logs it and each alert, returns the pairs in breach. Raises
    DatabaseUnavailable when the ledger cannot be read."""
    started = time.monotonic()
    seen = await shares(services.get(Database), config.window_s, config.tasks, config.failing)
    alerts = breaches(seen, config)
    for s in alerts:
        logs.warning(log, "inference.provider_alert", task=s.task, provider=s.provider, calls=s.calls,
                     failed=s.failed, share=round(s.failed_share, 2), window_s=int(config.window_s))
    logs.info(log, "inference.watch", pairs=len(seen), alerts=len(alerts),
              duration_ms=int((time.monotonic() - started) * 1000))
    return alerts


async def run(config: WatchConfig, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Evaluate, wait `interval_s`, repeat, until cancelled."""
    failing = False
    while True:
        try:
            await evaluate(config)
            failing = False
        except DatabaseUnavailable:
            if not failing:
                logs.warning(log, "inference.watch_unavailable")
            failing = True
        await sleep(config.interval_s)
