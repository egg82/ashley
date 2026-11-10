"""The code host's tunables, data in `codehost.json` beside this module: how long a call may take (`timeout_s`), how
many projects (`projects_max`) and tree entries (`tree_max`) one answer holds (both at most `PAGE_MAX`, the page size
both forges allow), how many bytes of a file are fetched to read (`read_bytes`), and the largest archive fetched (`snapshot_max_bytes`, under what the object store takes)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("codehost.json")
PAGE_MAX = 100


@dataclass(frozen=True)
class CodeHostConfig:
    timeout_s: float
    projects_max: int
    tree_max: int
    read_bytes: int
    snapshot_max_bytes: int


def load() -> CodeHostConfig:
    """The tunables shipped in `codehost.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> CodeHostConfig:
    """A CodeHostConfig from parsed JSON. Raises ValueError for a missing or unknown key, a value that is not a
    positive integer (`timeout_s`: a positive number), or a page over `PAGE_MAX`."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("code host config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(CodeHostConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"code host config keys: missing {missing}, unknown {unknown}")
    counts = {n: _count(n, raw[n]) for n in names if n != "timeout_s"}
    timeout = raw["timeout_s"]
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not timeout > 0:
        raise ValueError("timeout_s: expected a positive number")
    config = CodeHostConfig(timeout_s=float(timeout), **counts)
    if max(config.projects_max, config.tree_max) > PAGE_MAX:
        raise ValueError(f"code host config: a page is at most {PAGE_MAX}")
    return config


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value
