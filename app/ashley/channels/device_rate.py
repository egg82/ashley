"""How often one device may call the API: data (`device_rate.json`) tuned from real use."""

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class Rate:
    """A device may make `max_requests` requests in each fixed window of `window_seconds`; both >= 1."""

    window_seconds: int
    max_requests: int


def load() -> Rate:
    """The rate shipped in `device_rate.json` beside this module. Raises ValueError when it is malformed."""
    return parse(json.loads(resources.files("ashley.channels").joinpath("device_rate.json").read_text()))


def parse(data: object) -> Rate:
    """A rate from JSON already parsed: `{"window_seconds": n, "max_requests": n}` and nothing else. Raises ValueError
    naming what is wrong otherwise."""
    raw: Any = data
    fields = dict[str, object](raw) if hasattr(raw, "keys") else {}
    if set(fields) != {"window_seconds", "max_requests"}:
        raise ValueError("device rate is an object with exactly window_seconds and max_requests")
    seconds, most = fields["window_seconds"], fields["max_requests"]
    if type(seconds) is not int or seconds < 1:
        raise ValueError("device rate window_seconds: expected an integer >= 1")
    if type(most) is not int or most < 1:
        raise ValueError("device rate max_requests: expected an integer >= 1")
    return Rate(seconds, most)
