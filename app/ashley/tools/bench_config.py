"""Her bench tools' tunables, data in `bench_tools.json` beside this module: how much of each piece's body `bench_read`
shows her, how much of one piece `bench_read_piece` shows (a piece longer than that she can read the start of but
not edit), how many of the bench's latest commands `bench_read` lists, and how many pieces she may add in the turn that opens a bench (`lead_adds`)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("bench_tools.json")


@dataclass(frozen=True)
class BenchToolsConfig:
    read_body_chars: int
    piece_chars: int
    recent_commands: int
    lead_adds: int


def load() -> BenchToolsConfig:
    """The tunables shipped in `bench_tools.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> BenchToolsConfig:
    """A BenchToolsConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, or a value is
    not a positive integer."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("bench tools config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(BenchToolsConfig)]
    if sorted(str(k) for k in raw) != sorted(names):
        raise ValueError(f"bench tools config keys are {names}")
    for name in names:
        if type(raw[name]) is not int or int(loose[name]) <= 0:
            raise ValueError(f"{name}: expected a positive integer")
    return BenchToolsConfig(**{name: int(loose[name]) for name in names})
