"""The People service (`ashley.services`): households, the people in them, and the accounts that name them elsewhere.
Callers import only this module and `model`; the Postgres implementation lives beside it. Reads only: people,
households and accounts are added by `python -m ashley.people` (its `--help` lists the commands).

Names are people's data, so they are never logged; ids are."""

from abc import abstractmethod

from ..services import Service
from .model import Account, Household, Person


class PeopleUnavailable(Exception):
    """The database could not be reached. Transient: the caller may retry."""


class People(Service):
    @classmethod
    def null(cls) -> "People":
        return NullPeople()

    @abstractmethod
    async def household(self, household_id: int) -> Household | None:
        """The household with everyone in it; None when no household has that id."""

    @abstractmethod
    async def person_for(self, system: str, external_id: str) -> Person | None:
        """The person an account on `system` belongs to; None when no account maps that id (an unknown account is never
        guessed to be anyone)."""

    @abstractmethod
    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        """Every account on `system` of the people in that household, ordered by id; empty when there are none or no
        such household."""


class NullPeople(People):
    """Knows no one: what an unwired process sees. Every call raises PeopleUnavailable, so a missing registration fails
    loudly instead of treating everyone as a stranger."""

    async def household(self, household_id: int) -> Household | None:
        raise PeopleUnavailable("People is not wired")

    async def person_for(self, system: str, external_id: str) -> Person | None:
        raise PeopleUnavailable("People is not wired")

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        raise PeopleUnavailable("People is not wired")
