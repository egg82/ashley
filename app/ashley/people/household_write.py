"""The HouseholdWriter service (`ashley.services`): a signed-in person sets their own household's timezone, profile,
locale, unit system and clock, and their own quiet hours. Kept apart from `People`, which channels read, so nothing that reads a household can
write it: only the household route and the wiring import this module (a boundary test holds that). Callers import only
this module and `model`; the Postgres implementation lives beside it.

The profile is people's data, so it is never logged; which fields changed is."""

from abc import abstractmethod

from ..services import Service
from .model import Household, HouseholdEdit, QuietHours
from .people import PeopleUnavailable


class HouseholdWriter(Service):
    @classmethod
    def null(cls) -> "HouseholdWriter":
        return NullHouseholdWriter()

    @abstractmethod
    async def put(self, household_id: int, person_id: int, edit: HouseholdEdit) -> Household | None:
        """Replace every field `edit` names on the household, already checked (`people.fields`), and answer it as stored
        with everyone in it; None when no household has that id. Raises PeopleUnavailable."""

    @abstractmethod
    async def put_quiet(self, household_id: int, person_id: int, quiet: QuietHours | None) -> bool:
        """Set the person's own quiet hours, already checked (`people.fields`), or clear them with None; whether a
        person of that household has that id. Raises PeopleUnavailable."""


class NullHouseholdWriter(HouseholdWriter):
    """What an unwired process sees: every call raises PeopleUnavailable."""

    async def put(self, household_id: int, person_id: int, edit: HouseholdEdit) -> Household | None:
        raise PeopleUnavailable("HouseholdWriter is not wired")

    async def put_quiet(self, household_id: int, person_id: int, quiet: QuietHours | None) -> bool:
        raise PeopleUnavailable("HouseholdWriter is not wired")
