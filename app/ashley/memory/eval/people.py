"""The write cases' household as a `People`, so a writer that asks `People` for names meets the cases' people rather
than whoever the database holds."""

from typing import Any

from ...people.model import Account, Household, Person
from ...people.people import People
from .write import HOUSEHOLD


class CasePeople(People):
    """Household `write.HOUSEHOLD`, in UTC, with the cases' `profile` and one person per entry of their `people`
    (`{"alana": 1}` is Alana, id 1). No accounts."""

    def __init__(self, data: dict[str, Any]) -> None:
        people = tuple(sorted((Person(i, HOUSEHOLD, name.capitalize()) for name, i in data["people"].items()),
                              key=lambda p: p.id))
        self._household = Household(HOUSEHOLD, "eval", "UTC", data.get("profile", ""), people)

    async def household(self, household_id: int) -> Household | None:
        return self._household if household_id == HOUSEHOLD else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()
