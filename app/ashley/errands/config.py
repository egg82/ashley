"""The errands tunables, data in `errands.json` beside this module: `tick_s` between sweeps, `batch` errands run per
tick, `max_attempts` before giving up, `max_age_s` a due errand stays worth doing, `claim_s` before a running one is
called interrupted, `context_turns` of the conversation a run reads, `max_tool_rounds` and `max_tool_result_chars`
for its tool loop, and `tell_max` results carried into one reply."""

import json
from dataclasses import dataclass
from pathlib import Path

FILE = Path(__file__).with_name("errands.json")


@dataclass(frozen=True)
class ErrandsConfig:
    tick_s: float
    batch: int
    max_attempts: int
    max_age_s: float
    claim_s: float
    context_turns: int
    max_tool_rounds: int
    max_tool_result_chars: int
    tell_max: int


def load() -> ErrandsConfig:
    """The tunables shipped in `errands.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    names = set(ErrandsConfig.__dataclass_fields__)
    if set(raw) != names:
        raise ValueError(f"errands.json has exactly {sorted(names)}")
    made = ErrandsConfig(float(raw["tick_s"]), int(raw["batch"]), int(raw["max_attempts"]), float(raw["max_age_s"]),
                         float(raw["claim_s"]), int(raw["context_turns"]), int(raw["max_tool_rounds"]),
                         int(raw["max_tool_result_chars"]), int(raw["tell_max"]))
    if min(raw.values()) <= 0:
        raise ValueError("errands tunables must be positive")
    return made


CONFIG = load()
