"""The Lexicons service (`ashley.services`): each household's pronunciation words (`lexicon.Lexicon`), kept beside its
profile and edited by any of its people in the web room. Read when a spoken reply is rendered and never held between
renders, so an edit applies to the next reply and one household's words never reach another's. A household starts with
none."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..services import Service
from .lexicon import EMPTY, Lexicon

MAX_ENTRIES = 200


class LexiconUnavailable(Exception):
    """The database could not be reached. Transient: the caller may retry."""


class LexiconFull(Exception):
    """A household already has `MAX_ENTRIES` words and the put named a new one."""


@dataclass(frozen=True)
class Entry:
    """`updated_by` is a person id, None once they are gone."""

    real: str
    spoken: str
    updated_at: datetime
    updated_by: int | None


class Lexicons(Service):
    @classmethod
    def null(cls) -> "Lexicons":
        return NullLexicons()

    @abstractmethod
    async def of(self, household_id: int | None) -> Lexicon:
        """The household's words; empty for no household, for one with none, and when they cannot be read (logged
        `lexicon.unreadable`), so a spoken reply is never lost to its pronunciation. Never raises."""

    @abstractmethod
    async def entries(self, household_id: int) -> tuple[Entry, ...]:
        """The household's words by `real`. Raises LexiconUnavailable."""

    @abstractmethod
    async def put(self, household_id: int, person_id: int, real: str, spoken: str) -> Entry:
        """Add `real` or replace its spelling. Raises ValueError for an entry `lexicon.refusal` names, LexiconFull,
        LexiconUnavailable."""

    @abstractmethod
    async def remove(self, household_id: int, person_id: int, real: str) -> bool:
        """Whether the household had `real`. Raises LexiconUnavailable."""


class NullLexicons(Lexicons):
    """What an unwired process sees: no words anywhere, and nothing can be edited."""

    async def of(self, household_id: int | None) -> Lexicon:
        return EMPTY

    async def entries(self, household_id: int) -> tuple[Entry, ...]:
        raise LexiconUnavailable("Lexicons is not wired")

    async def put(self, household_id: int, person_id: int, real: str, spoken: str) -> Entry:
        raise LexiconUnavailable("Lexicons is not wired")

    async def remove(self, household_id: int, person_id: int, real: str) -> bool:
        raise LexiconUnavailable("Lexicons is not wired")
