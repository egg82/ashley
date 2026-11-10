"""Which wake rule answers an event: the one wake piece (`ashley.workshop.wake_rule`) for that event on the
household's open benches. None is `no_rule`; more than one is `ambiguous`, and no turn runs rather than one picked."""

from typing import Literal

from ... import services
from ...workshop.wake_rule import WakeRule, rule_of
from ...workshop.workshop import Workshop

KIND = "wake"


async def rule_for(household_id: int, event: str) -> WakeRule | Literal["no_rule", "ambiguous"]:
    """Raises WorkshopUnavailable."""
    pieces = await services.get(Workshop).of_kind(household_id, KIND)
    rules = [r for r in (rule_of(p.body) for p in pieces) if r is not None and r.event == event]
    if not rules:
        return "no_rule"
    return rules[0] if len(rules) == 1 else "ambiguous"
