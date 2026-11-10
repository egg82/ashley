"""The Looks service (`ashley.services`): the record of every look she took, the picture she was given kept with the
person turn that asked, so the page shows what she saw and a count of a turn's looks survives the pod that took them.
The picture's bytes are in the object store under `ashley.files.intake.key_of(household, sha256)`; this holds the row
that names them. Callers import only this module; `postgres.PostgresLooks` implements it."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..services import Service


class LooksUnavailable(Exception):
    """The record could not be read or written."""


@dataclass(frozen=True)
class NewLook:
    """A look about to be kept: the household; the conversation, person turn and tool call that asked for it; the bench
    and the piece looked at (None for the whole bench); and the picture, as its `sha256` in the object store, its
    `media_type` and `size`."""

    household_id: int
    conversation_id: int
    turn_id: int
    call_id: str
    bench_id: int
    piece_id: int | None
    sha256: str
    media_type: str
    size: int


@dataclass(frozen=True)
class Look:
    """A kept look."""

    id: int
    household_id: int
    conversation_id: int
    turn_id: int
    call_id: str
    bench_id: int
    piece_id: int | None
    sha256: str
    media_type: str
    size: int
    looked_at: datetime


class Looks(Service):
    @classmethod
    def null(cls) -> "Looks":
        return NullLooks()

    @abstractmethod
    async def keep(self, look: NewLook) -> int:
        """Record `look` and return its id. A turn's call keeps one look: a second for the same call (a read run again
        after a resume) replaces the first. Raises LooksUnavailable."""

    @abstractmethod
    async def taken(self, household_id: int, turn_id: int, except_call: str) -> int:
        """How many looks person turn `turn_id` has kept for calls other than `except_call`. Raises LooksUnavailable."""

    @abstractmethod
    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Look]:
        """Every look the household's conversation asked for, oldest first (by id), in one read; none when it asked for
        none or is not the household's. Raises LooksUnavailable."""


class NullLooks(Looks):
    """Keeps nothing, so no look is taken: what an unwired process sees."""

    async def keep(self, look: NewLook) -> int:
        raise LooksUnavailable("Looks is not wired")

    async def taken(self, household_id: int, turn_id: int, except_call: str) -> int:
        raise LooksUnavailable("Looks is not wired")

    async def in_conversation(self, household_id: int, conversation_id: int) -> list[Look]:
        return []
