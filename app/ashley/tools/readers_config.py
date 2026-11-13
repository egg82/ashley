"""The readers' tunables, data in `readers.json` beside this module: how many readers one call may send, how many rounds
of reads each may make before it must report, how much of each result it reads, and how much of its report crosses back
to her."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("readers.json")


@dataclass(frozen=True)
class ReadersConfig:
    max_readers: int
    max_rounds: int
    result_chars: int
    report_chars: int


def load() -> ReadersConfig:
    """The tunables shipped in `readers.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> ReadersConfig:
    """A ReadersConfig from JSON already parsed. Raises ValueError when it is not an object, a key is missing or unknown,
    or a value is not a positive integer."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("readers config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(ReadersConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"readers config keys: missing {missing}, unknown {unknown}")
    return ReadersConfig(**{n: _count(n, raw[n]) for n in names})


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value
