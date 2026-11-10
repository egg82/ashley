"""A `People` that knows one household, so a tool that shows times can find the household's zone."""

from dataclasses import dataclass

from ashley.people.model import Household, Person
from ashley.people.people import Account, People


@dataclass
class OneHome(People):
    home: Household | None

    async def household(self, household_id: int) -> Household | None:
        return self.home

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()
