"""When something she proposed to a person may be carried out: from a person turn stored after the one she proposed it
in (turn ids, never her words), within a time limit. Every proposal she keeps for a person's OK is judged by it (`proposals.refusal`)."""

from datetime import datetime, timedelta
from typing import Literal

Refusal = Literal["none", "expired", "same_turn", "not_yours"]


def gate(proposed_turn_id: int, proposed_at: datetime, turn_id: int, now: datetime, ttl_s: float) -> Refusal | None:
    """Why a proposal made in turn `proposed_turn_id` at `proposed_at` cannot be carried out in the person turn `turn_id`
    at `now`, None when it can."""
    if turn_id <= proposed_turn_id:
        return "same_turn"
    if now - proposed_at > timedelta(seconds=ttl_s):
        return "expired"
    return None
