"""Initiative policies for suites that test something else: `speaking()` lets every reply out that says it is worth
saying, at any moment, so a suite's outcome never rests on the shipped weights or a roll."""

from typing import Any

from ashley.initiative.initiative import Scored
from ashley.initiative.weights import parse

FLOOR = -1e9


def weights(**changed: Any) -> dict[str, Any]:
    """Weights as JSON with every weight zero and every clearing score full, with `changed` keys replaced."""
    raw: dict[str, Any] = {
        "threshold": FLOOR,
        "heard": {"weight": 0.0, "full_at_s": 3600},
        "night": {"weight": 0.0, "from_hour": 22, "to_hour": 7},
        "others_home": {"weight": 0.0, "cap": 3},
        "greeted": {"weight": 0.0, "within_s": 3600},
        "spoke": {"weight": 0.0, "within_s": 3600},
        "odds": [{"from": FLOOR, "full": 1.0, "short": 0.0, "silent": 0.0}],
    }
    return {**raw, **changed}


def speaking() -> Scored:
    return Scored(parse(weights()))
