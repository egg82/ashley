"""Opening connections by the port they serve, not by the service's kind."""

from .. import services
from .connections import Connections
from .kinds import ConnectionKinds
from .model import Opened, Port


async def opened_all(connections: Connections, port: Port, household_id: int,
                     person_id: int | None = None) -> tuple[Opened, ...]:
    """Every connection visible to `person_id` whose kind implements `port`, in kind registration order, then label,
    then id. Raises ConnectionsUnavailable."""
    held = await connections.of_household(household_id, person_id)
    found: list[Opened] = []
    for kind in services.get(ConnectionKinds).of_port(port):
        for connection in (c for c in held if c.kind == kind.name):
            opened = await connections.opened(connection.id, household_id, person_id)
            if opened is not None:
                found.append(opened)
    return tuple(found)


async def opened(connections: Connections, port: Port, household_id: int, person_id: int | None = None) -> Opened | None:
    """The first of `opened_all`; None when there is none. Raises ConnectionsUnavailable."""
    found = await opened_all(connections, port, household_id, person_id)
    return found[0] if found else None
