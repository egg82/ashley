"""Opening connections by the port they serve, not by the service's kind. A household's switches (`settings.PORTS_OFF`)
are honoured here and nowhere else: a connection with a port switched off is as if its kind did not implement it, and
the port's combine rule (`model.PORTS`) says whether the connections left serve together or the first alone."""

from .. import services
from .connections import Connections
from .kinds import ConnectionKinds
from .model import PORTS, Opened, Port
from .settings_read import SettingsReader


async def opened_all(connections: Connections, port: Port, household_id: int, person_id: int | None = None,
                     everyone: bool = False) -> tuple[Opened, ...]:
    """The connections visible to `person_id` that serve `port` (its kind implements it and the household has not
    switched it off there), in kind registration order, then label, then id: all of them for a `combine` port, the
    first alone for a `one` port. With `everyone`, the household's and every person's connections are read, each opened as
    its own person, for a port the household looks through as a whole. Raises ConnectionsUnavailable."""
    held = await (connections.of_everyone(household_id) if everyone else connections.of_household(household_id, person_id))
    off = await services.get(SettingsReader).ports_off(household_id)
    found: list[Opened] = []
    for kind in services.get(ConnectionKinds).of_port(port):
        for connection in (c for c in held if c.kind == kind.name and port not in off.get(c.id, ())):
            opened = await connections.opened(connection.id, household_id,
                                              connection.person_id if everyone else person_id)
            if opened is not None:
                found.append(opened)
                if PORTS[port] == "one":
                    return tuple(found)
    return tuple(found)


async def opened(connections: Connections, port: Port, household_id: int, person_id: int | None = None) -> Opened | None:
    """The first of `opened_all`; None when there is none. Raises ConnectionsUnavailable."""
    found = await opened_all(connections, port, household_id, person_id)
    return found[0] if found else None
