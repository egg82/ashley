"""The OutsideRecord service (`ashley.services`): what a turn that had read outside words did without asking, and which
house lists it wrote (`decisions.md`, "A turn that has read outside words asks before it does anything consequential the
person did not ask for"). `Outside` writes it and reads it back for the receipts beside her reply; `house_ask` reads `written`.

`DoneAction`s are kept `actions_keep_s` and pruned by the write that adds the next; a list entity written by a tainted
turn counts as outside for `writes_keep_s` and is pruned the same way. Neither holds arguments or results."""

from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..services import Service


class OutsideRecordUnavailable(Exception):
    """The database could not be reached or written. Transient."""


@dataclass(frozen=True)
class DoneAction:
    """A change the turn `turn_id` of `conversation_id`, for `person_id` of `household_id`, made with no OK: `tool`, a
    code-written `summary`, its `tier`, and `reason` and `explanation` when the judge ran it (None for tier `runs`);
    `label` is the headline the person was shown for it (`ToolSpec.label`, else the shipped `unlabelled`)."""

    household_id: int
    person_id: int
    conversation_id: int
    turn_id: int
    tool: str
    summary: str
    tier: str
    reason: str | None
    explanation: str | None
    at: datetime
    label: str


@dataclass(frozen=True)
class Recorded:
    """A stored `action` and its row `id`, which only grows."""

    id: int
    action: DoneAction


class OutsideRecord(Service):
    @classmethod
    def null(cls) -> "OutsideRecord":
        return NullOutsideRecord()

    @abstractmethod
    async def done(self, action: DoneAction) -> None:
        """Store `action`, and drop the actions older than `actions_keep_s`. Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        """The turn's actions, oldest first. Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def of_person(self, household_id: int, person_id: int, limit: int) -> tuple[Recorded, ...]:
        """At most `limit` of the actions made for `person_id` of `household_id`, newest first. Never another person's
        or household's. Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        """Note that a tainted turn wrote the list `entity` at `at`, and drop the notes older than `writes_keep_s`.
        Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        """Whether any of `entities` was written by a tainted turn within `writes_keep_s`. Raises
        OutsideRecordUnavailable."""


class NullOutsideRecord(OutsideRecord):
    """What an unwired process sees: every call raises, so nothing is recorded as safe."""

    async def done(self, action: DoneAction) -> None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def of_person(self, household_id: int, person_id: int, limit: int) -> tuple[Recorded, ...]:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        raise OutsideRecordUnavailable("the outside record is not wired")
