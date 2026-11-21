"""A shadow run of an automation piece: the piece installed into Home Assistant as a separate automation that keeps its
triggers and conditions and replaces its actions with one that fires the event `ashley_shadow`, so Home Assistant, never
her code, decides when the piece would have fired, and she records each firing beside what the automation it would
replace did (`shadows`). The run is an ordinary Install of a proposal marked `shadow` (`commands.Propose`), carried out
by `install_piece`; it ends by its Undo or, after `Settings.duration_s`, by the shadow job (`shadow_job`).

The event's data is the bench, piece and version, numbers only: pieces are numbered per bench, and the version says which
text fired. Tunables are data, `shadow.json`: `duration_s` a run lasts, `keep_s` its firings are kept, `max_events` a run
keeps at most (the oldest go first), `shown` firings a bench's piece lists, `tick_s` between the job's passes."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .json_shape import object_of

FILE = Path(__file__).with_name("shadow.json")
EVENT = "ashley_shadow"
MARK = "Shadow: "
_ID = "ashley_shadow_"


@dataclass(frozen=True)
class Settings:
    duration_s: float
    keep_s: float
    max_events: int
    shown: int
    tick_s: float


def load() -> Settings:
    """The tunables in `shadow.json`. Raises ValueError unless it has exactly the five keys, each a number above 0."""
    raw = object_of(json.loads(FILE.read_text()))
    keys = ("duration_s", "keep_s", "max_events", "shown", "tick_s")
    if raw is None or set(raw) != set(keys):
        raise ValueError(f"shadow.json has exactly {', '.join(keys)}")
    numbers = [float(v) for v in (raw[k] for k in keys) if isinstance(v, int | float) and not isinstance(v, bool) and v > 0]
    if len(numbers) != len(keys):
        raise ValueError("shadow.json's values are numbers above 0")
    return Settings(float(numbers[0]), float(numbers[1]), int(numbers[2]), int(numbers[3]), float(numbers[4]))


def id_for(automation_id: str) -> str:
    """The id a piece's shadow is installed under, given the id its real install uses; never equal to it."""
    return _ID + automation_id.removeprefix("ashley_")


def config_of(config: Mapping[str, Any], bench_id: int, piece_id: int, version: int) -> dict[str, Any]:
    """`config` as its shadow: its triggers, conditions, mode and variables kept, its alias marked, and its actions
    replaced by the one event that says the piece would have fired."""
    kept = {k: v for k, v in config.items() if k not in ("actions", "alias", "description")}
    event = {"event": EVENT, "event_data": {"bench": bench_id, "piece": piece_id, "version": version}}
    return {**kept, "alias": MARK + str(config.get("alias", "")), "actions": [event]}
