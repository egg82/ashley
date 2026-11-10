"""The Connections service (`ashley.services`): a household's connections to services outside her, each a base URL
and a secret sealed at rest (`sealing`), addressed by its id. A member of the household adds, replaces, renames and
removes one from the web app; her tools open one to call the service for that household. An owner (the household, or
for a kind a person may hold, the person) holds up to the kind's `most` of a kind, each under its own label. A connection is
visible to a person when it is the household's or theirs; any other does not exist as far as they can tell. Secrets are
never logged and never leave through `of_household`; logs carry household and connection ids, kinds and counts, never
labels."""

from abc import abstractmethod

from ..services import Service
from .model import Connection, Holder, Kind, Opened


class ConnectionsUnavailable(Exception):
    """The connections could not be read or written: no database, or no key to seal and open them with. Transient
    for the database; for the key, until `CONNECTIONS_KEY` is set."""


class LabelTaken(Exception):
    """The owner already has a connection of this kind with that label."""

    def __init__(self, kind: Kind) -> None:
        super().__init__(kind)
        self.kind = kind


class TooMany(Exception):
    """The owner already holds as many connections of this kind as it allows (`ConnectionKind.most`)."""

    def __init__(self, kind: Kind) -> None:
        super().__init__(kind)
        self.kind = kind


class NotAdder(Exception):
    """A connection the household holds is taken back only by the person who added it."""


class Connections(Service):
    @classmethod
    def null(cls) -> "Connections":
        return NullConnections()

    @abstractmethod
    def can_open(self) -> bool:
        """Whether this process holds the key that seals and opens secrets, so connections can be added and read."""

    @abstractmethod
    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        """The connections visible to `person_id`, by kind, then label, then id. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        """That one connection with its secret, when it is visible to `person_id` (the household's, or theirs); None
        otherwise. Raises ConnectionsUnavailable, also when the stored secret does not open under this key (logged
        `connections.unsealable`)."""

    @abstractmethod
    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        """Add a connection of `kind`, held by `holder` (the kind's default when None): the household, or `added_by`
        as a person's own; `checked_at` and `added_at` are now. The caller has already checked that the service
        answers with it. Logs `connections.added`.
        Raises ConnectionsUnavailable; ValueError for an unknown kind, a holder the kind does not allow or an
        `added_by` not of that household; LabelTaken
        when the owner has one of that kind with that label; TooMany when the owner holds the kind's `most`. Nothing
        is written for any of them."""

    async def move(self, connection_id: int, household_id: int, person_id: int, holder: Holder) -> Connection | None:
        """Hand a connection visible to `person_id` to the household, or take one back as theirs, sealing its secret
        again bound to its new holder and setting each of its resources shared (to the household) or kept (back to a
        person), in one transaction. Moving to the holder it already has changes nothing. None when it is not visible
        to them. Logs `connections.moved`. Raises ConnectionsUnavailable; ValueError for a holder the kind does not
        allow; NotAdder for taking back one `person_id` did not add; LabelTaken when the new holder has one of that
        kind under that label; TooMany when the new holder holds the kind's `most`. Nothing is written for any of
        them. A store that keeps no holders raises ConnectionsUnavailable."""
        raise ConnectionsUnavailable("this store cannot move connections")

    @abstractmethod
    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        """A new address and secret for a connection visible to `person_id`, keeping its id and label; `checked_at`
        and `added_at` are now and `added_by` is `person_id`. None, and nothing written, when it is not visible to
        them. Logs `connections.replaced`. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def relabel(self, connection_id: int, household_id: int, person_id: int, label: str) -> Connection | None:
        """A new label for a connection visible to `person_id`; None when it is not visible to them. Logs
        `connections.relabeled`. Raises ConnectionsUnavailable; LabelTaken when the owner has another of that kind with
        that label."""

    @abstractmethod
    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        """Add the household's connection of `kind` from her own setup, with no one as its adder and an empty label,
        only where it has none of that kind: None, and nothing written, when it already has one or there is no such household. Logs
        `connections.seeded`. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        """Remove a connection visible to `person_id`; False when it is not visible to them. Logs
        `connections.removed`. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def answered(self, connection_id: int) -> None:
        """The service answered with this connection now: `checked_at` moves to now. Raises
        ConnectionsUnavailable."""


class NullConnections(Connections):
    """No key, or nothing wired: nothing can be added and none are read, so no tool that needs one is offered."""

    def can_open(self) -> bool:
        return False

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        raise ConnectionsUnavailable("connections are not wired")

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        raise ConnectionsUnavailable("connections are not wired")

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def relabel(self, connection_id: int, household_id: int, person_id: int, label: str) -> Connection | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        raise ConnectionsUnavailable("connections are not wired")

    async def answered(self, connection_id: int) -> None:
        raise ConnectionsUnavailable("connections are not wired")
