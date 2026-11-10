"""The outside record in lists, for tests that wire `OutsideRecord` without a database: what `done` was given, and the
list entities `wrote` named."""

from collections.abc import Sequence
from datetime import datetime

from ashley.senses.outside_record import DoneAction, OutsideRecord


class MemoryRecord(OutsideRecord):
    """The outside record in lists: what `done` was given, and the list entities `wrote` named."""

    def __init__(self) -> None:
        self.actions: list[DoneAction] = []
        self.writes: set[tuple[int, str]] = set()

    async def done(self, action: DoneAction) -> None:
        self.actions.append(action)

    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        return tuple(a for a in self.actions if (a.conversation_id, a.turn_id) == (conversation_id, turn_id))

    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        self.writes.add((household_id, entity))

    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        return any((household_id, e) in self.writes for e in entities)
