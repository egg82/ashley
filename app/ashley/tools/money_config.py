"""The money tools' tunables, data in `money.json` beside this module: how long a call to Sure may take, how many
accounts and categories one answer holds, how many transactions one answer holds unless she asks for fewer
(`transactions_default`) and at most (`transactions_max`, which Sure's own page limit of 100 bounds), how long a
search may be, and how many transactions one categorisation may name (`categorise_max`, one call to Sure each)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("money.json")
SURE_PAGE_MAX = 100


@dataclass(frozen=True)
class MoneyConfig:
    timeout_s: float
    accounts_max: int
    categories_max: int
    transactions_default: int
    transactions_max: int
    search_chars: int
    categorise_max: int


def load() -> MoneyConfig:
    """The tunables shipped in `money.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> MoneyConfig:
    """A MoneyConfig from JSON already parsed. Raises ValueError when a key is missing or unknown, a value is not a
    positive integer (`timeout_s`: a positive number), a page is over Sure's 100, or the default is over the max."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("money config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(MoneyConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"money config keys: missing {missing}, unknown {unknown}")
    counts = {n: _count(n, raw[n]) for n in names if n != "timeout_s"}
    config = MoneyConfig(timeout_s=_number("timeout_s", raw["timeout_s"]), **counts)
    if max(config.accounts_max, config.categories_max, config.transactions_max) > SURE_PAGE_MAX:
        raise ValueError(f"money config: a page is at most {SURE_PAGE_MAX}")
    if config.transactions_default > config.transactions_max:
        raise ValueError("money config: transactions_default is over transactions_max")
    return config


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
