"""The Accounts service (`ashley.services`): a signed-in person's own accounts, which they may read, link and unlink
themselves. Kept apart from `People`, which channels read and only the admin CLI writes, so nothing that reads people
can write them. Callers import only this module and `model`; the Postgres implementation lives beside it.

An account's external id and handle are people's data: never logged, except as a short hash of the external id."""

from abc import abstractmethod
from typing import Literal

from ..services import Service
from .model import Account
from .people import PeopleUnavailable

Linked = Literal["linked", "taken"]
"""`linked`: the account is now this person's (or already was); `taken`: another person has it, and nothing changed."""


class Accounts(Service):
    @classmethod
    def null(cls) -> "Accounts":
        return NullAccounts()

    @abstractmethod
    async def of(self, person_id: int) -> tuple[Account, ...]:
        """Every account of that person, on every system, ordered by id. Raises PeopleUnavailable."""

    @abstractmethod
    async def link(self, person_id: int, system: str, external_id: str, handle: str) -> Linked:
        """Map `system`'s `external_id` to the person, in their household, with `handle` as its name there now. An
        account already theirs keeps its id and takes the new handle. Raises PeopleUnavailable."""

    @abstractmethod
    async def unlink(self, person_id: int, account_id: int, system: str) -> bool:
        """Remove the account `account_id` when it is that person's and on `system`; False, removing nothing,
        otherwise. Raises PeopleUnavailable."""


class NullAccounts(Accounts):
    """What an unwired process sees: every call raises PeopleUnavailable."""

    async def of(self, person_id: int) -> tuple[Account, ...]:
        raise PeopleUnavailable("Accounts is not wired")

    async def link(self, person_id: int, system: str, external_id: str, handle: str) -> Linked:
        raise PeopleUnavailable("Accounts is not wired")

    async def unlink(self, person_id: int, account_id: int, system: str) -> bool:
        raise PeopleUnavailable("Accounts is not wired")
