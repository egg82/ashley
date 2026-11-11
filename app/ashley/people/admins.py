"""The Admins service (`ashley.services`): who is an admin of the deployment, written. An admin may change what every
household shares (`decisions.md`, "An admin changes what the deployment shares"). Kept apart from `People`, which
channels read, so nothing that reads people can make one an admin: only the sign-in and people routes and the wiring
import this module (a boundary test holds that). Callers import only this module; the Postgres implementation lives
beside it.

Every write is serialised against every other admin write, so two at once on either site can neither leave the
deployment with no admin nor bootstrap two. One log line per change, with person ids only."""

from abc import abstractmethod
from typing import Literal

from ..services import Service
from .people import PeopleUnavailable

Outcome = Literal["set", "not_found", "last_admin"]
"""`set`: the person is now as asked (also when they already were); `not_found`: no person of that household has that
id; `last_admin`: refused, since it would leave the deployment with no admin."""


class Admins(Service):
    @classmethod
    def null(cls) -> "Admins":
        return NullAdmins()

    @abstractmethod
    async def claim_first(self, person_id: int) -> bool:
        """Make the person an admin when the deployment has none: True when this call made them one, False when an admin
        already existed (them included). Of any number of calls at once, at most one answers True. Raises
        PeopleUnavailable."""

    @abstractmethod
    async def grant(self, person_id: int) -> bool:
        """Make the person an admin, as the sign-in provider's admin group says they are: True when they were not one
        before. Raises PeopleUnavailable."""

    @abstractmethod
    async def put(self, household_id: int, person_id: int, admin: bool, by: int) -> Outcome:
        """Set whether a person of `household_id` is an admin, as the admin `by` asked. Revoking the last admin is
        refused. Raises PeopleUnavailable."""


class NullAdmins(Admins):
    """What an unwired process sees: every call raises PeopleUnavailable, so nobody becomes an admin by accident."""

    async def claim_first(self, person_id: int) -> bool:
        raise PeopleUnavailable("Admins is not wired")

    async def grant(self, person_id: int) -> bool:
        raise PeopleUnavailable("Admins is not wired")

    async def put(self, household_id: int, person_id: int, admin: bool, by: int) -> Outcome:
        raise PeopleUnavailable("Admins is not wired")
