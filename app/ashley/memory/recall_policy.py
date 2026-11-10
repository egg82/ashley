"""How much one recall returns, as data (`recall.json` beside this module)."""

import json
from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class RecallPolicy:
    """`limit` caps the full-text matches one recall (or one `similar`) returns; `vector_k` is how many facts nearest
    by embedding are added to them."""

    limit: int
    vector_k: int


def load() -> RecallPolicy:
    """The policy shipped in `recall.json` beside this module."""
    return RecallPolicy(**json.loads(resources.files("ashley.memory").joinpath("recall.json").read_text()))
