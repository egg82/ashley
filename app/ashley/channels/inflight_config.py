"""The tunables of work in flight, data in `inflight.json`: `claim_s`, how long a claim lasts past its last renewal;
`poll_s`, how often the resume sweep looks; `max_attempts`, the runners a turn may have before it is given up; `batch`,
the most claimed per sweep; `unavailable_retry_s`, how long a turn whose model could not be reached waits before the
sweep takes it again (it counts as an attempt)."""

import json
from dataclasses import dataclass
from pathlib import Path

FILE = Path(__file__).with_name("inflight.json")


@dataclass(frozen=True)
class Config:
    claim_s: float
    poll_s: float
    max_attempts: int
    batch: int
    unavailable_retry_s: float = 120.0


def load() -> Config:
    """The tunables shipped in `inflight.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != {"claim_s", "poll_s", "max_attempts", "batch", "unavailable_retry_s"}:
        raise ValueError("inflight.json has exactly claim_s, poll_s, max_attempts, batch and unavailable_retry_s")
    made = Config(float(raw["claim_s"]), float(raw["poll_s"]), int(raw["max_attempts"]), int(raw["batch"]),
                  float(raw["unavailable_retry_s"]))
    if min(made.claim_s, made.poll_s, made.max_attempts, made.batch, made.unavailable_retry_s) <= 0:
        raise ValueError("inflight tunables must be positive")
    return made


CONFIG = load()
