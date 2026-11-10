"""How a device's screen starts: the pieces of `screen_seed.json`, each `{"kind", "size"}`, added by her in that order
when the screen is first laid out. Nothing household-specific: the controls piece's body is the device's own list."""

import json
from dataclasses import replace
from pathlib import Path

from . import screen_controls
from .commands import Add
from .decide import EMPTY, Accepted, BenchState, replay
from .json_shape import list_of, object_of
from .model import HER, SIZES, Size, Text
from .rules import Rules

SEED_FILE = Path(__file__).with_name("screen_seed.json")
TITLE = "Screen"
"""The title every screen bench has, which nothing shows."""


def seed_of(raw: object, rules: Rules) -> tuple[tuple[str, Size], ...]:
    """The kinds and sizes in a parsed `screen_seed.json`. Raises ValueError for a shape other than a list of
    `{"kind", "size"}` that replays accepted under `rules`."""
    items = list_of(raw)
    if not items:
        raise ValueError("screen_seed.json is a non-empty list")
    seed = tuple(_entry(item, rules) for item in items)
    laid = replay(_adds(seed, rules, "[]"), rules, TITLE)
    if not all(isinstance(d, Accepted) for d in laid) or not rules.required <= {p.kind for p in laid[-1].state.pieces}:
        raise ValueError("screen_seed.json is not accepted by the screen rules, or leaves out a required kind")
    return seed


def _entry(item: object, rules: Rules) -> tuple[str, Size]:
    fields = object_of(item) or {}
    kind, size = fields.get("kind"), fields.get("size")
    if set(fields) != {"kind", "size"} or kind not in rules.kinds or size not in SIZES:
        raise ValueError("screen_seed.json entries are {kind, size} of a screen kind and a size")
    return str(kind), next(s for s in SIZES if s == size)


def commands(seed: tuple[tuple[str, Size], ...], rules: Rules, controls: tuple[screen_controls.Control, ...]) -> tuple[Add, ...]:
    """The Adds that lay the seed out, her own, the controls piece holding `controls`."""
    return _adds(seed, rules, screen_controls.encode(controls))


def state_of(seed: tuple[tuple[str, Size], ...], rules: Rules, controls: tuple[screen_controls.Control, ...]) -> BenchState:
    """The screen after the seed's Adds, from an empty one titled `TITLE`."""
    state = replace(EMPTY, title=TITLE)
    for decision in replay(commands(seed, rules, controls), rules, TITLE):
        state = decision.state
    return state


def _adds(seed: tuple[tuple[str, Size], ...], rules: Rules, controls_body: str) -> tuple[Add, ...]:
    return tuple(Add(HER, kind, Text(rules.kinds[kind].label, controls_body if rules.kinds[kind].format == "controls" else ""), size)
                 for kind, size in seed)


def load(rules: Rules) -> tuple[tuple[str, Size], ...]:
    """The seed shipped beside this module. Raises ValueError when it is malformed."""
    return seed_of(json.loads(SEED_FILE.read_text()), rules)
