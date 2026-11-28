"""The OutsideRecord service (`ashley.services`): what she did that nobody asked for in that turn, and which house lists
a tainted turn wrote (`decisions.md`, "A turn that has read outside words asks before it does anything consequential the
person did not ask for", "What she did on her own is one record"). A `DoneAction` is a change a tainted turn made with no
OK, or a change any turn no person's message started made (a wake, a reminder or errand round, a watch, a bench's
reaction), each with its `cause` and, where the change has an inverse, its `undo`. `Outside` writes it and reads it back
for the receipts beside her reply; `house_ask` reads `written`.

`DoneAction`s are kept `actions_keep_s` and pruned by the write that adds the next; a list entity written by a tainted
turn counts as outside for `writes_keep_s` and is pruned the same way. Neither holds arguments or results. What she kept
quiet on her own (`QuietEntry`) is a third table of the same record, kept `quiet_keep_s`."""

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


UndoneHow = Literal["undoing", "undone", "waiting_on_you", "gone"]
"""Where an Undo taken stands: `undoing` while a route carries it out (a claim, which lapses after the claim's seconds so
a pod that stopped partway leaves it takeable again); `undone`, carried out; `waiting_on_you`, carried out as a proposal
the person agrees to (a delete); `gone`, its target was no longer there, so nothing was done."""

Settled = Literal["undone", "waiting_on_you", "gone"]
"""How an Undo that was carried out ended: an `UndoneHow` other than `undoing`."""


@dataclass(frozen=True)
class Undone:
    """That a row's undo was taken: when (`at`), by which person (`by`) and `how` it stands."""

    at: datetime
    by: int
    how: UndoneHow


def undone_of(at: datetime | None, by: int | None, how: str | None) -> Undone | None:
    """The stored fields as `Undone`; None when none is stored, or a state this release does not know."""
    for known in get_args(UndoneHow):
        if known == how and at is not None and by is not None:
            return Undone(at, by, known)
    return None


@dataclass(frozen=True)
class Recorded:
    """A stored `action` and its row `id`, which only grows; `undone` when its undo was taken."""

    id: int
    action: DoneAction
    undone: Undone | None = None


Why = Literal["quiet_hours", "not_greeting", "below_threshold", "rolled_silent", "said_none"]
"""Why Initiative kept an unprompted turn quiet: `quiet_hours`, the person's own; `not_greeting`, a turn with no moment to
score, on which she set `says` to none; `below_threshold`, the moment's score under the threshold (no roll made);
`rolled_silent`, the score cleared it and the seeded roll came out silent; `said_none`, the plan let her speak and she set
`says` to none. Never her words."""


@dataclass(frozen=True)
class QuietEntry:
    """A turn of `conversation_id` in `household_id`, for `person_id` (None when it was the household's), kept quiet at
    `at` for `why`; `score` is the moment's initiative score when it had one; `cause` is the record that started the
    turn, None when its builder names none."""

    household_id: int
    person_id: int | None
    conversation_id: int
    at: datetime
    why: Why
    score: float | None = None
    cause: Cause | None = None


@dataclass(frozen=True)
class QuietLately:
    """What was kept quiet for a person within the keep: how many (`count`), the newest `latest` first, and `id`, the
    newest row's."""

    count: int
    id: int
    latest: tuple[QuietEntry, ...]


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
    async def one(self, household_id: int, person_id: int, action_id: int) -> Recorded | None:
        """The action `action_id` when it was made for `person_id` of `household_id` and is still kept; None otherwise.
        Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def claim_undo(self, household_id: int, person_id: int, action_id: int, claim_s: float) -> bool:
        """Mark the undo of `person_id`'s action `action_id` as `undoing` by them, now; whether it was marked. Only an
        action with an undo, never undone or left `undoing` more than `claim_s` ago, is: two routes taking one Undo at
        once cannot both carry it out. Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def settle_undo(self, action_id: int, how: Settled | None) -> None:
        """End the claim on `action_id`'s undo as `how`, now, or give it up with None (nothing was done, so its Undo is
        offered again). A row not `undoing` is left as it is. Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        """Note that a tainted turn wrote the list `entity` at `at`, and drop the notes older than `writes_keep_s`.
        Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        """Whether any of `entities` was written by a tainted turn within `writes_keep_s`. Raises
        OutsideRecordUnavailable."""

    @abstractmethod
    async def quieted(self, entry: QuietEntry) -> None:
        """Store `entry`, and drop the entries older than `quiet_keep_s`. Raises OutsideRecordUnavailable."""

    @abstractmethod
    async def quiet_of_person(self, household_id: int, person_id: int, latest: int) -> QuietLately | None:
        """How many entries are kept for `person_id` of `household_id` and the newest `latest` of them; None when there
        are none. Never another person's or household's. Raises OutsideRecordUnavailable."""


class NullOutsideRecord(OutsideRecord):
    """What an unwired process sees: every call raises, so nothing is recorded as safe."""

    async def done(self, action: DoneAction) -> None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def of_turn(self, conversation_id: int, turn_id: int) -> tuple[DoneAction, ...]:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def of_person(self, household_id: int, person_id: int, limit: int) -> tuple[Recorded, ...]:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def one(self, household_id: int, person_id: int, action_id: int) -> Recorded | None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def claim_undo(self, household_id: int, person_id: int, action_id: int, claim_s: float) -> bool:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def settle_undo(self, action_id: int, how: Settled | None) -> None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def wrote(self, household_id: int, entity: str, at: datetime) -> None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def written(self, household_id: int, entities: Sequence[str]) -> bool:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def quieted(self, entry: QuietEntry) -> None:
        raise OutsideRecordUnavailable("the outside record is not wired")

    async def quiet_of_person(self, household_id: int, person_id: int, latest: int) -> QuietLately | None:
        raise OutsideRecordUnavailable("the outside record is not wired")
