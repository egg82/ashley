"""The ConnectionResources service (`ashley.services`): what a connection reaches, as its service names it (a Gmail
account's one mailbox), each resource shared with the household or kept by the connection's owner
(`decisions.md`, "Who holds a connection, and who sees what it reaches"). Holding is the connection's and seeing is the
resource's: every resource of a household's connection is shared, since the household already holds the login, and a
person's own are kept until they share them. Logs carry connection ids, counts and whether a resource is shared, never
a name or ref."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..services import Service
from .connections import ConnectionsUnavailable
from .model import Connection, Listed, Resource, ResourceKind


class HeldByHousehold(Exception):
    """A resource of a household's connection cannot be kept: the household already holds the login."""


@dataclass(frozen=True)
class Use:
    """What a turn is, to the resource gate. `speaker_id` is the person only when the channel itself names them
    (`Inbound.speaker_id`, never a voice match); `alone` is whether the reply reaches that speaker alone
    (`ashley.channels.audience.owner_alone`)."""

    household_id: int
    speaker_id: int | None
    alone: bool


@dataclass(frozen=True)
class Usable:
    """A resource a turn may use, with its connection. `opens_for` is the person to open the connection's login for:
    its owner (None for a household's), which is how a turn that is not the owner's reaches a shared resource and
    nothing else."""

    connection: Connection
    resource: Resource

    @property
    def opens_for(self) -> int | None:
        return self.connection.person_id


def permits(use: Use, changing: bool, connection: Connection, resource: Resource, member: bool) -> bool:
    """Whether a turn of `use` may use `resource` of `connection`; `member` is whether the speaker is a person of the
    household. A shared resource, or any resource of a household's connection, is open to reading on any turn of the
    household and to changing when a member speaks; a kept one only to its owner where the reply reaches them alone."""
    if resource.shared or connection.person_id is None:
        return member if changing else True
    return use.alone and use.speaker_id == connection.person_id


class ConnectionResources(Service):
    @classmethod
    def null(cls) -> "ConnectionResources":
        return NullConnectionResources()

    @abstractmethod
    async def of_household(self, household_id: int, person_id: int | None = None) -> Mapping[int, tuple[Resource, ...]]:
        """The resources of each connection visible to `person_id` (`Connections.of_household`), by connection id; a
        connection with none is absent. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def listed(self, connection_id: int, household_id: int, found: Sequence[Listed]) -> tuple[Resource, ...]:
        """Make the connection's stored resources what its service names now: a new one is shared when the connection
        is the household's and kept when it is a person's, one already stored keeps its flag and takes the new name,
        one not named is dropped. The caller read `found` from the service successfully. Empty, and nothing written,
        for a connection not of that household. Raises ConnectionsUnavailable."""

    @abstractmethod
    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str,
                    shared: bool) -> Resource | None:
        """Share the resource `ref` of a connection visible to `person_id` with the household, or keep it. Visible to a
        person means theirs (only the owner shares) or the household's. None when there is no such connection or
        resource. Raises HeldByHousehold for keeping a household connection's. Logs `connections.resource_shared`.
        Raises ConnectionsUnavailable."""

    @abstractmethod
    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        """The resources of `kind` a turn of `use` may use, by connection kind, label, then id. Reading: a shared one on
        any turn of the household, a kept one only where the reply reaches its owner alone. Changing: a shared one when
        the channel names a speaker of the household, a kept one on the same terms as reading it. Raises
        ConnectionsUnavailable."""


class NullConnectionResources(ConnectionResources):
    async def of_household(self, household_id: int, person_id: int | None = None) -> Mapping[int, tuple[Resource, ...]]:
        raise ConnectionsUnavailable("connections are not wired")

    async def listed(self, connection_id: int, household_id: int, found: Sequence[Listed]) -> tuple[Resource, ...]:
        raise ConnectionsUnavailable("connections are not wired")

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str,
                    shared: bool) -> Resource | None:
        raise ConnectionsUnavailable("connections are not wired")

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        raise ConnectionsUnavailable("connections are not wired")
