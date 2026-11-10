"""Her Claude Code tools' tunables, data in `claude_code.json` beside this module: how many lines of a screen a read
takes when none are named (`read_lines`) and at most (`read_lines_max`, the bridge's own ceiling), and the longest prompt she sends (`prompt_chars`, the
bridge's own)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("claude_code.json")


@dataclass(frozen=True)
class ClaudeCodeConfig:
    read_lines: int
    read_lines_max: int
    prompt_chars: int


def load() -> ClaudeCodeConfig:
    """The tunables shipped in `claude_code.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> ClaudeCodeConfig:
    """A ClaudeCodeConfig from parsed JSON. Raises ValueError for a missing or unknown key, a value that is not a
    positive integer, or a `read_lines` over `read_lines_max`."""
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError("claude code config is an object")
    raw = dict[object, object](loose)
    names = [f.name for f in fields(ClaudeCodeConfig)]
    missing = [n for n in names if n not in raw]
    unknown = sorted(str(k) for k in raw if k not in names)
    if missing or unknown:
        raise ValueError(f"claude code config keys: missing {missing}, unknown {unknown}")
    values = {n: raw[n] for n in names}
    for name, value in values.items():
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name}: expected a positive integer")
    config = ClaudeCodeConfig(**{n: int(str(v)) for n, v in values.items()})
    if config.read_lines > config.read_lines_max:
        raise ValueError("read_lines is at most read_lines_max")
    return config
