"""A `People` that knows one household, whose locale a test sets."""

from dataclasses import dataclass

from ashley import services
from ashley.people.model import Account, Household, Person
from ashley.people.people import People


@dataclass
class LocaleHome(People):
    home: Household

    async def household(self, household_id: int) -> Household | None:
        return self.home if household_id == self.home.id else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


def wire(household_id: int, locale: str) -> None:
    services.register(People, LocaleHome(Household(household_id, "home", "Europe/Berlin", "", (), locale)))


def unwire() -> None:
    services.unregister(People)
