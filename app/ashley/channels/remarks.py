"""The Remarks service (`ashley.services`): the remarks nobody asked for that she was allowed to make
(`ashley.initiative.remark`), so the cap per person per day and "never the same line" are counted from what she did,
not asked of a model. A remark is claimed before her turn and settled after it with the fingerprint of the line that
went out, or none when she kept quiet. Only ids, times and fingerprints are stored; never what was said."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..services import Service


class RemarksUnavailable(Exception):
    """The database could not be read or written. Transient."""


@dataclass(frozen=True)
class Before:
    """What came before a remark for a person: `sent`, how many claimed since the count's start that went out or are
    not yet settled; `said`, the fingerprints of every line sent in the household since the repeat window's start."""

    sent: int
    said: tuple[str, ...]


class Remarks(Service):
    @classmethod
    def null(cls) -> "Remarks":
        return NullRemarks()

    @abstractmethod
    async def before(self, household_id: int, person_id: int, count_since: datetime, said_since: datetime) -> Before:
        """Raises RemarksUnavailable."""

    @abstractmethod
    async def claim(self, household_id: int, person_id: int, source: str, at: datetime) -> bool:
        """True for exactly one caller per household and `source` (the message's stable id), until pruned; False when
        already claimed. Raises RemarksUnavailable."""

    @abstractmethod
    async def settle(self, household_id: int, source: str, line: str | None) -> None:
        """Record how the claimed remark ended: `line`, the fingerprint of what went out, or None when nothing did.
        Nothing for a remark never claimed or settled already. Raises RemarksUnavailable."""

    @abstractmethod
    async def prune(self, before: datetime) -> int:
        """Delete remarks claimed before `before`; how many. Raises RemarksUnavailable."""


class NullRemarks(Remarks):
    """What an unwired process sees: nothing can be counted, so no remark is allowed."""

    async def before(self, household_id: int, person_id: int, count_since: datetime, said_since: datetime) -> Before:
        raise RemarksUnavailable("no remarks store is wired")

    async def claim(self, household_id: int, person_id: int, source: str, at: datetime) -> bool:
        raise RemarksUnavailable("no remarks store is wired")

    async def settle(self, household_id: int, source: str, line: str | None) -> None:
        raise RemarksUnavailable("no remarks store is wired")

    async def prune(self, before: datetime) -> int:
        raise RemarksUnavailable("no remarks store is wired")
