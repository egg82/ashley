"""Printables' tunables, data in `printables.json` beside this module: the GraphQL endpoint and the site's address,
the only hosts a design file may be downloaded from (`file_hosts`, compared to a URL's parsed hostname), how long an
API call (`timeout_s`) and a file download (`download_timeout_s`) may take, how many redirects a download may follow,
how many results a search shows, how much of a summary, and how many of a model's files a search result lists."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("printables.json")


@dataclass(frozen=True)
class PrintablesConfig:
    api_url: str
    site_url: str
    file_hosts: frozenset[str]
    timeout_s: float
    results: int
    summary_chars: int
    listed_files: int
    download_timeout_s: float
    max_redirects: int


def load() -> PrintablesConfig:
    """The tunables shipped in `printables.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> PrintablesConfig:
    """A PrintablesConfig from parsed JSON. Raises ValueError for a missing or unknown key, an address that is not a
    non-empty string, a host list that is not non-empty strings, or a number that is not positive (the timeouts: a
    number; the rest: an integer)."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("printables config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(PrintablesConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"printables config keys: missing {missing}, unknown {unknown}")
    return PrintablesConfig(
        api_url=_text("api_url", raw["api_url"]), site_url=_text("site_url", raw["site_url"]).rstrip("/"),
        file_hosts=_hosts(raw["file_hosts"]),
        timeout_s=_number("timeout_s", raw["timeout_s"]),
        results=_count("results", raw["results"]), summary_chars=_count("summary_chars", raw["summary_chars"]),
        listed_files=_count("listed_files", raw["listed_files"]),
        download_timeout_s=_number("download_timeout_s", raw["download_timeout_s"]),
        max_redirects=_count("max_redirects", raw["max_redirects"]))


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: expected a non-empty string")
    return value.strip()


def _hosts(value: object) -> frozenset[str]:
    loose: Any = value
    if not isinstance(value, list) or not value:
        raise ValueError("file_hosts: expected a non-empty list of host names")
    return frozenset(_text("file_hosts", h).lower() for h in list[object](loose))


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)
