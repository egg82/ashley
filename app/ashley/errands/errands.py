"""The Errands service (`ashley.services`): asks she could not carry out for want of a tool source, held until the
source answers (`decisions.md`, "What she could not do for want of a source, she does once it answers, and says so next
time"). An errand is `due`, then `running` under one claim, then `done` with its result or `given_up` with a reason.
Every method that settles a claimed errand takes the `attempt` it was claimed at and changes nothing when the row is no
longer `running` at that attempt, so a late run cannot overwrite a sweep's verdict."""

from abc import abstractmethod
from collections.abc import Collection

from ..services import Service
from .model import Counts, Done, Errand, Reason, State


class ErrandsUnavailable(Exception):
    """The store could not be reached or written. Transient."""


class Errands(Service):
    @classmethod
    def null(cls) -> "Errands":
        return NullErrands()

    @abstractmethod
    async def owe(self, household_id: int, asker_id: int, conversation_id: int, turn_id: int, source: str) -> int:
        """Store a `due` errand for the person turn `turn_id`, keeping that turn's visibility; the same turn again
        returns the existing errand's id. Raises ErrandsUnavailable."""

    @abstractmethod
    async def claim(self, answering: Collection[str], max_age_s: float) -> Errand | None:
        """In one transaction take the oldest `due` errand whose source is in `answering` and is younger than
        `max_age_s`, `FOR UPDATE SKIP LOCKED`, and set it `running` with `attempts + 1` and `claimed_at`; None when
        there is none. Raises ErrandsUnavailable."""

    @abstractmethod
    async def due_sources(self, max_age_s: float) -> frozenset[str]:
        """The distinct sources of `due` errands younger than `max_age_s`: what a `claim` could take. Raises
        ErrandsUnavailable."""

    @abstractmethod
    async def release(self, errand_id: int, attempt: int, max_attempts: int) -> State:
        """Put a run that could not finish back to `due`, or `given_up` with reason `attempts` once `attempt` reaches
        `max_attempts`; the state it is in afterwards. Changes nothing unless the row is `running` at `attempt`, and
        then answers the state it has. Raises LookupError for an unknown errand, ErrandsUnavailable."""

    @abstractmethod
    async def finish(self, errand_id: int, attempt: int, result: str) -> None:
        """Set it `done` with `result` in one transaction, under the same condition as `release`. Raises
        ErrandsUnavailable."""

    @abstractmethod
    async def give_up(self, errand_id: int, attempt: int, reason: Reason) -> None:
        """Set it `given_up` with `reason`, under the same condition as `release`. Raises ErrandsUnavailable."""

    @abstractmethod
    async def sweep(self, claim_s: float, max_age_s: float) -> Counts:
        """`running` errands claimed more than `claim_s` ago become `given_up` with reason `interrupted`; `due` ones
        created more than `max_age_s` ago, reason `expired`. Raises ErrandsUnavailable."""

    @abstractmethod
    async def untold(self, hearer: int, limit: int, owner_only: bool = True) -> tuple[Done, ...]:
        """The `hearer`'s own `done` errands not yet told that `ashley.hearing.MAY_HEAR` lets them hear, oldest first,
        at most `limit`. `owner_only` is whether only the hearer will hear the reply; False withholds private
        results. Raises ErrandsUnavailable."""

    @abstractmethod
    async def told(self, errand_ids: Collection[int]) -> None:
        """Set `told_at` on each errand not already told. Raises ErrandsUnavailable."""


class NullErrands(Errands):
    """What an unwired process sees: every call raises, so nothing is owed or told by mistake."""

    async def owe(self, household_id: int, asker_id: int, conversation_id: int, turn_id: int, source: str) -> int:
        raise ErrandsUnavailable("errands are not wired")

    async def claim(self, answering: Collection[str], max_age_s: float) -> Errand | None:
        raise ErrandsUnavailable("errands are not wired")

    async def due_sources(self, max_age_s: float) -> frozenset[str]:
        raise ErrandsUnavailable("errands are not wired")

    async def release(self, errand_id: int, attempt: int, max_attempts: int) -> State:
        raise ErrandsUnavailable("errands are not wired")

    async def finish(self, errand_id: int, attempt: int, result: str) -> None:
        raise ErrandsUnavailable("errands are not wired")

    async def give_up(self, errand_id: int, attempt: int, reason: Reason) -> None:
        raise ErrandsUnavailable("errands are not wired")

    async def sweep(self, claim_s: float, max_age_s: float) -> Counts:
        raise ErrandsUnavailable("errands are not wired")

    async def untold(self, hearer: int, limit: int, owner_only: bool = True) -> tuple[Done, ...]:
        raise ErrandsUnavailable("errands are not wired")

    async def told(self, errand_ids: Collection[int]) -> None:
        raise ErrandsUnavailable("errands are not wired")
