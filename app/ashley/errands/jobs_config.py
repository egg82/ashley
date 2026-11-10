"""The bench jobs' tunables, data in `jobs.json` beside this module.

`tick_s` between runner ticks; `claim_s` before a claimed job is called lapsed; `max_attempts` claims before a lapsed
job fails; `max_group` jobs one hand-off may start; `group_timeout_min` a group may stay unsettled; per worker
`max_running` jobs a person may have unfinished and `deadline_min` a job may take; `max_pieces_in`, `max_bytes_in` and
`brief_chars` a job is given at most; `max_outputs` files and `result_chars` of summary taken back; `agent_max_tool_rounds`
of an agent's loop and `tool_result_chars` of each tool result it reads; `max_runs_per_turn` bench runs her own turn makes before the next is handed off; `kind_extensions`, the file
extension a text piece of each kind goes as (`txt` for a kind not listed), and `extensions`, the one of each media type
a large piece's bytes may have (`bin` for one not listed)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bench_job_model import WORKERS, Worker

FILE = Path(__file__).with_name("jobs.json")
_COUNTS = ("max_attempts", "max_group", "group_timeout_min", "max_pieces_in", "max_bytes_in", "max_outputs",
           "brief_chars", "result_chars", "agent_max_tool_rounds", "tool_result_chars", "max_runs_per_turn")


@dataclass(frozen=True)
class JobsConfig:
    tick_s: float
    claim_s: float
    max_attempts: int
    max_group: int
    group_timeout_min: int
    max_running: Mapping[Worker, int]
    deadline_min: Mapping[Worker, int]
    max_pieces_in: int
    max_bytes_in: int
    max_outputs: int
    brief_chars: int
    result_chars: int
    agent_max_tool_rounds: int
    tool_result_chars: int
    max_runs_per_turn: int
    kind_extensions: Mapping[str, str]
    extensions: Mapping[str, str]


def load() -> JobsConfig:
    """The tunables shipped in `jobs.json`. Raises ValueError when one is missing, unknown or not positive."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> JobsConfig:
    """A JobsConfig from parsed JSON. Raises ValueError for a missing or unknown key, or a number that is not positive."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("jobs config is an object")
    raw = dict[str, Any](loose)
    names = {*_COUNTS, "tick_s", "claim_s", "max_running", "deadline_min", "kind_extensions", "extensions"}
    if set(raw) != names:
        raise ValueError(f"jobs.json has exactly {sorted(names)}")
    c = {n: _count(n, raw[n]) for n in _COUNTS}
    return JobsConfig(
        _number("tick_s", raw["tick_s"]), _number("claim_s", raw["claim_s"]), c["max_attempts"], c["max_group"],
        c["group_timeout_min"], _workers("max_running", raw["max_running"]),
        _workers("deadline_min", raw["deadline_min"]), c["max_pieces_in"], c["max_bytes_in"], c["max_outputs"],
        c["brief_chars"], c["result_chars"], c["agent_max_tool_rounds"], c["tool_result_chars"],
        c["max_runs_per_turn"],
        _extensions("kind_extensions", raw["kind_extensions"]), _extensions("extensions", raw["extensions"]))


def _count(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{name}: expected a positive number")
    return float(value)


def _workers(name: str, value: object) -> Mapping[Worker, int]:
    loose: Any = value
    if not isinstance(value, dict) or set(dict[str, Any](loose)) != set(WORKERS):
        raise ValueError(f"{name} has exactly {list(WORKERS)}")
    mapping = dict[str, Any](loose)
    return {w: _count(f"{name}.{w}", mapping[w]) for w in WORKERS}


def _extensions(name: str, value: object) -> Mapping[str, str]:
    loose: Any = value
    if not isinstance(value, dict):
        raise ValueError(f"{name} is an object of names to extensions")
    found = dict[str, Any](loose)
    if not all(isinstance(v, str) and v.isalnum() for v in found.values()):
        raise ValueError(f"{name} maps each name to an alphanumeric extension")
    return {k: str(v) for k, v in found.items()}


CONFIG = load()
