"""What the Errands store hands out."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

State = Literal["due", "running", "done", "given_up"]
Reason = Literal["attempts", "expired", "interrupted", "refused"]
Visibility = Literal["shared", "private"]


@dataclass(frozen=True)
class Errand:
    """A claimed errand: the ask is the person turn `turn_id` of `conversation_id`, `source` the key of the tool source
    it needed, and `attempt` which run this is (1 for the first)."""

    id: int
    household_id: int
    asker_id: int
    conversation_id: int
    turn_id: int
    source: str
    attempt: int
    visibility: Visibility


@dataclass(frozen=True)
class Done:
    """A finished errand: `result` is what she says she did, `visibility` how widely the ask was heard."""

    id: int
    asker_id: int
    source: str
    result: str
    visibility: Visibility
    finished_at: datetime


@dataclass(frozen=True)
class Counts:
    """What a sweep gave up on: `interrupted` running errands and `expired` due ones."""

    interrupted: int
    expired: int
