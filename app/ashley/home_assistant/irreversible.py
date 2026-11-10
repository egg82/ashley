"""Which changes to the house need a person's OK first, as data in `irreversible.json` beside this module: shell-style
patterns over operation keys (`house.py`). A delete, a removal and the actions that restart, stop or destroy data are
named there; anything else she does on her own."""

import json
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from .ha_json import listed, names, obj

FILE = Path(__file__).with_name("irreversible.json")


@dataclass(frozen=True)
class Irreversible:
    operations: tuple[str, ...]

    def covers(self, operation: str) -> bool:
        """Whether the operation key matches any pattern."""
        return any(fnmatchcase(operation, pattern) for pattern in self.operations)


def load() -> Irreversible:
    """The patterns shipped in `irreversible.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> Irreversible:
    """Irreversible from JSON already parsed. Raises ValueError unless it is an object whose only key `operations` is a
    non-empty list of non-empty strings."""
    top = obj(data)
    if not isinstance(data, dict) or set(top) != {"operations"}:
        raise ValueError("irreversible.json is an object with the key operations and no other")
    items = listed(top["operations"])
    patterns = names(items)
    if not items or len(patterns) != len(items):
        raise ValueError("operations: expected a non-empty list of non-empty strings")
    return Irreversible(patterns)
