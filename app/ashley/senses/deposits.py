"""The Deposits service (`ashley.services`): event reminders armed on a deposit rule, and how far the deposit sense has
read each household's Sure. An armed reminder is a `wakes` row of kind `reminder` and trigger `event`: unsettled, never
due, listed with the household's reminders, cancelled like any (`Wakes.cancel`). A match stores an ordinary once
reminder beside it, which the `wakes` singleton fires and the push singleton delivers; the armed one stays armed, so
every match fires (`decisions.md`, "A reminder can wait on a deposit")."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from ..services import Service
from .deposit_rule import DepositRule, Landed
from .wakes import Reminder


class DepositsUnavailable(Exception):
    """The database could not be reached or written. Transient."""


@dataclass(frozen=True)
class Armed:
    """An armed event reminder: its wake `id`, `household_id`, `rule` and `armed_at`, the instant it was set."""

    id: int
    household_id: int
    rule: DepositRule
    armed_at: datetime


class Deposits(Service):
    @classmethod
    def null(cls) -> "Deposits":
        return NullDeposits()

    @abstractmethod
    async def arm(self, reminder: Reminder, rule: DepositRule) -> int:
        """Store `reminder` (its `due_at` is when it is set; it has no repeat) as armed on `rule`; its wake id. Raises
        ValueError for a brief outside 1 to `MAX_BRIEF` characters or holding a NUL, or a repeat; DepositsUnavailable."""

    @abstractmethod
    async def armed(self) -> tuple[Armed, ...]:
        """Every unsettled armed reminder, oldest first. Raises DepositsUnavailable."""

    @abstractmethod
    async def fire(self, armed_id: int, transaction_id: str, landed: Landed | None = None) -> bool:
        """Store the once reminder for Sure transaction `transaction_id` matching armed reminder `armed_id`, due now, with
        its person, asker and brief, and the deposit `landed` it fires for. True for the call that stored it; False, changing nothing, when this transaction
        fired it before (so a retry, a second reader or a new holder fires once) or the armed reminder is settled or
        gone. Raises DepositsUnavailable."""

    @abstractmethod
    async def read_through(self, household_id: int) -> date | None:
        """The day the sense last finished reading the household's Sure on, None before it has. Raises
        DepositsUnavailable."""

    @abstractmethod
    async def advance(self, household_id: int, day: date) -> None:
        """Record that the household's Sure has been read through `day`; never moves back. Raises
        DepositsUnavailable."""


class NullDeposits(Deposits):
    """What an unwired process sees: every call raises, so a deposit is never taken in and quietly dropped."""

    async def arm(self, reminder: Reminder, rule: DepositRule) -> int:
        raise DepositsUnavailable("deposits are not wired")

    async def armed(self) -> tuple[Armed, ...]:
        raise DepositsUnavailable("deposits are not wired")

    async def fire(self, armed_id: int, transaction_id: str, landed: Landed | None = None) -> bool:
        raise DepositsUnavailable("deposits are not wired")

    async def read_through(self, household_id: int) -> date | None:
        raise DepositsUnavailable("deposits are not wired")

    async def advance(self, household_id: int, day: date) -> None:
        raise DepositsUnavailable("deposits are not wired")
