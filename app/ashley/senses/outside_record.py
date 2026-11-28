"""The OutsideRecord service (`ashley.services`): what she did that nobody asked for in that turn, and which house lists
a tainted turn wrote (`decisions.md`, "A turn that has read outside words asks before it does anything consequential the
person did not ask for", "What she did on her own is one record"). A `DoneAction` is a change a tainted turn made with no
OK, or a change any turn no person's message started made (a wake, a reminder or errand round, a watch, a bench's
reaction), each with its `cause` and, where the change has an inverse, its `undo`. `Outside` writes it and reads it back
for the receipts beside her reply; `house_ask` reads `written`.

`DoneAction`s are kept `actions_keep_s` and pruned by the write that adds the next; a list entity written by a tainted
turn counts as outside for `writes_keep_s` and is pruned the same way. Neither holds arguments or results."""

from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

from ..services import Service
from ..undo import Undo


class OutsideRecordUnavailable(Exception):
    """The database could not be reached or written. Transient."""


CauseKind = Literal["wake", "reminder", "open_errand", "standing_errand", "watch", "bench", "turn"]
"""What started the turn a change was made in, each naming the record its `Cause.id` is: `wake`, a household event's
wake (a `wakes` row); `reminder`, `open_errand` and `standing_errand`, an occurrence of a reminder, of a check of an
errand or of a round of a standing errand (the wake id `/api/work` lists it by); `watch`, a watch's wake (the watch's
id); `bench`, a bench's reaction to what its owner did (the bench's id); `turn`, the person's own turn that read
outside words (its turn id)."""


@dataclass(frozen=True)
class Cause:
    """Why she made a change no one asked for in that turn: the `kind` of record and its `id`."""

    kind: CauseKind
    id: int


def cause_of(kind: str | None, id_: int | None) -> Cause | None:
    """The stored fields as a `Cause`; None when none is stored, or a kind this release does not know."""
    for known in get_args(CauseKind):
        if known == kind and id_ is not None:
            return Cause(known, id_)
    return None


@dataclass(frozen=True)
class DoneAction:
    """A change the turn `turn_id` of `conversation_id`, for `person_id` of `household_id`, made with no OK: `tool`, a
    code-written `summary`, its `tier`, and `reason` and `explanation` when the judge ran it (None for tier `runs`, which
    is also the tier of every change of a turn that read no outside words); `label` is the headline the person was shown
    for it (`ToolSpec.label`, else the shipped `unlabelled`). `cause` is what started the turn, None for a row kept
    before causes were. `undo` is how the change is taken back; None means it has no inverse (a send, a delete, a
    replaced config, a moved mail) or was kept before undos were, and the board offers no Undo for it."""

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
    cause: Cause | None = None
    undo: Undo | None = None


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
