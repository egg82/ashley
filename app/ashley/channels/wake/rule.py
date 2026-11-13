"""Which wake rule answers a wake: of the wake pieces (`ashley.workshop.wake_rule`) on the household's open benches
that answer its event, `who` and `what` (`WakeRule.answers`), the most specific (`WakeRule.specificity`, how many of
`who` and `what` it sets). None is `no_rule`; more than one at the top is `ambiguous`, and no turn runs rather than one
picked.

Logs `wakes.rule` with the wake and household ids, the outcome (`one`, `no_rule` or `ambiguous`), the piece that
answers (None unless one does), the specificity at the top and how many rules share it; never a field of the wake or
of a rule."""

import logging
from collections.abc import Sequence
from typing import Literal

from ... import logs, services
from ...senses.wakes import Wake
from ...workshop.wake_rule import WakeRule, rule_of
from ...workshop.workshop import Workshop

KIND = "wake"

log = logging.getLogger("ashley.channels.wake")


async def rule_for(wake_id: int, wake: Wake) -> WakeRule | Literal["no_rule", "ambiguous"]:
    """Raises WorkshopUnavailable."""
    pieces = await services.get(Workshop).of_kind(wake.household_id, KIND)
    best = top([(p.piece_id, r) for p in pieces if (r := rule_of(p.body)) is not None], wake)
    outcome: WakeRule | Literal["no_rule", "ambiguous"] = (
        "no_rule" if not best else "ambiguous" if len(best) > 1 else best[0][1])
    logs.info(log, "wakes.rule", wake=wake_id, household=wake.household_id,
              outcome=outcome if isinstance(outcome, str) else "one", piece=best[0][0] if len(best) == 1 else None,
              specificity=best[0][1].specificity if best else None, tied=len(best))
    return outcome


def top(rules: Sequence[tuple[int, WakeRule]], wake: Wake) -> list[tuple[int, WakeRule]]:
    """The `(piece id, rule)` pairs of `rules` that answer `wake` at the highest specificity any of them has."""
    found = [(i, r) for i, r in rules if r.answers(wake.event, wake.who, wake.what)]
    most = max((r.specificity for _, r in found), default=0)
    return [(i, r) for i, r in found if r.specificity == most]
