"""The look-up's tunables, data in `look_up.json` beside this module: how many rounds of searches it may make before it
must answer, how much of each search result it reads, how much of its answer crosses back to her, and how a page is
read (`page_fetch`): how long it may take, how many redirects it may follow, how many bytes of its body are read and
how many characters of its text are kept."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("look_up.json")


@dataclass(frozen=True)
class LookUpConfig:
    max_rounds: int
    result_chars: int
    answer_chars: int
    max_sources: int
    page_timeout_s: float
    max_redirects: int
    page_bytes: int
    page_chars: int


def load() -> LookUpConfig:
    """The tunables shipped in `look_up.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> LookUpConfig:
    """A LookUpConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, or a value is not a
    positive integer (`page_timeout_s`: a positive number)."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("look-up config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(LookUpConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"look-up config keys: missing {missing}, unknown {unknown}")
    counts = {n: _count(n, raw[n]) for n in names if n != "page_timeout_s"}
    return LookUpConfig(page_timeout_s=_number("page_timeout_s", raw["page_timeout_s"]), **counts)


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
