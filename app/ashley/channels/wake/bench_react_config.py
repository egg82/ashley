"""The bench reaction's tunables, data in `bench_react.json` beside this module. `pause_s`: how long a person's commands
on a bench stay quiet before she reacts. `max_reactions` per `window_s` on one bench bounds how often. `scan`: how
many quiet benches are looked at per sweep, `batch`: how many of them she reacts to. `listed`: the most commands one
reaction is handed by name. `keep_s`: how long a bench's older reaction records are kept."""

import json
from dataclasses import dataclass
from pathlib import Path

FILE = Path(__file__).with_name("bench_react.json")
_KEYS = ("pause_s", "max_reactions", "window_s", "scan", "batch", "listed", "keep_s")


@dataclass(frozen=True)
class Config:
    pause_s: float
    max_reactions: int
    window_s: float
    scan: int
    batch: int
    listed: int
    keep_s: float


def load() -> Config:
    """The tunables shipped in `bench_react.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != set(_KEYS):
        raise ValueError(f"bench_react.json has exactly {', '.join(_KEYS)}")
    made = Config(float(raw["pause_s"]), int(raw["max_reactions"]), float(raw["window_s"]), int(raw["scan"]),
                  int(raw["batch"]), int(raw["listed"]), float(raw["keep_s"]))
    if min(made.pause_s, made.max_reactions, made.window_s, made.scan, made.batch, made.listed, made.keep_s) <= 0:
        raise ValueError("bench reaction tunables must be positive")
    return made


CONFIG = load()
