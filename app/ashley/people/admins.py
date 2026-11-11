"""The Admins service (`ashley.services`): who is an admin of the deployment, as the app records it (`people.admin`),
written. An admin may change what every household shares (`decisions.md`, "An admin changes what the deployment
shares"). It is used only while `ADMIN_GROUP` is unset; set, the provider's group decides at each sign-in
(`ashley.signin.sessions.Sessions.open`) and nothing here is called. Kept apart from `People`, which
channels read, so nothing that reads people can make one an admin: only the sign-in and people routes and the wiring
import this module (a boundary test holds that). Callers import only this module; the Postgres implementation lives
beside it.

Every write is serialised against every other admin write, so two at once on either site can neither leave the
deployment with no admin nor make two people the first. One log line per change, with person ids only."""

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
    async def ensure_one(self, household_id: int) -> int | None:
        """When no person of the deployment is an admin, make the earliest person of `household_id` (the lowest id) one
        and answer their id; None when an admin already existed or that household has nobody. Any number of calls at
        once make at most one admin. Raises PeopleUnavailable."""

    @abstractmethod
    async def put(self, household_id: int, person_id: int, admin: bool, by: int) -> Outcome:
        """Set whether a person of `household_id` is an admin, as the admin `by` asked. Revoking the last admin is
        refused. Raises PeopleUnavailable."""


class NullAdmins(Admins):
    """What an unwired process sees: every call raises PeopleUnavailable, so nobody becomes an admin by accident."""

    async def ensure_one(self, household_id: int) -> int | None:
        raise PeopleUnavailable("Admins is not wired")

    async def put(self, household_id: int, person_id: int, admin: bool, by: int) -> Outcome:
        raise PeopleUnavailable("Admins is not wired")
