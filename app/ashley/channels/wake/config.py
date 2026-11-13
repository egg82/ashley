"""The `wakes` singleton's tunables, data in `wakes.json` beside this module, read by the runner and by the push and
satellites singletons that deliver fired reminders."""

import json
from dataclasses import dataclass
from pathlib import Path

FILE = Path(__file__).with_name("wakes.json")


@dataclass(frozen=True)
class Config:
    """`fire_attempts`: how many times a reminder whose firing could not run is fired before it is settled `failed`,
    `retry_s` apart; `retry_s` is also how long a reminder's undelivered push waits before it is tried again, for
    `deliver_for_s` after it fired. A reminder routed to a room or screen is tried there `device_tries` times,
    `device_retry_s` apart, before its phone."""

    poll_s: float
    batch: int
    max_age_s: float
    keep_s: float
    fire_attempts: int
    retry_s: float
    deliver_for_s: float
    device_tries: int
    device_retry_s: float


_KEYS = ("poll_s", "batch", "max_age_s", "keep_s", "fire_attempts", "retry_s", "deliver_for_s", "device_tries",
         "device_retry_s")


def load() -> Config:
    """The tunables shipped in `wakes.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != set(_KEYS):
        raise ValueError(f"wakes.json has exactly {', '.join(_KEYS)}")
    made = Config(float(raw["poll_s"]), int(raw["batch"]), float(raw["max_age_s"]), float(raw["keep_s"]),
                  int(raw["fire_attempts"]), float(raw["retry_s"]), float(raw["deliver_for_s"]),
                  int(raw["device_tries"]), float(raw["device_retry_s"]))
    if min(made.poll_s, made.batch, made.max_age_s, made.keep_s, made.fire_attempts, made.retry_s,
           made.deliver_for_s, made.device_tries, made.device_retry_s) <= 0:
        raise ValueError("wake tunables must be positive")
    return made


CONFIG = load()
