"""The printing and stock tools' tunables, data in `printing.json` beside this module: how long a call to Bambuddy may
take, how many printers one answer holds, how many spools, how many library files unless she asks for fewer
(`files_default`) and at most (`files_max`), and how long a search may be."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("printing.json")


@dataclass(frozen=True)
class PrintingConfig:
    timeout_s: float
    printers_max: int
    spools_max: int
    files_default: int
    files_max: int
    search_chars: int


def load() -> PrintingConfig:
    """The tunables shipped in `printing.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> PrintingConfig:
    """A PrintingConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a value is not a
    positive integer (`timeout_s`: a positive number), or the default is over the max."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("printing config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(PrintingConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"printing config keys: missing {missing}, unknown {unknown}")
    counts = {n: _count(n, raw[n]) for n in names if n != "timeout_s"}
    config = PrintingConfig(timeout_s=_number("timeout_s", raw["timeout_s"]), **counts)
    if config.files_default > config.files_max:
        raise ValueError("printing config: files_default is over files_max")
    return config


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
