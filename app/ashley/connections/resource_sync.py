"""Reading what a connection reaches from its service and storing it (`ConnectionResources.listed`): when a connection is
stored, when the room is opened, and for a connection stored before its kind listed resources."""

import logging

from .. import logs, services
from .kinds import ConnectionKinds, ResourcesUnavailable
from .model import Opened, Resource
from .resources import ConnectionResources

log = logging.getLogger("ashley.connections")


async def sync(opened: Opened) -> tuple[Resource, ...] | None:
    """The connection's resources now, as the service names them; None when its kind lists none or the service could
    not say, in which case what is stored stays. Raises ConnectionsUnavailable."""
    connection = opened.connection
    kind = services.get(ConnectionKinds).get(connection.kind)
    if kind is None or kind.resources is None:
        return None
    try:
        found = await kind.resources(opened)
    except ResourcesUnavailable as e:
        logs.warning(log, "connections.resources_unavailable", connection=connection.id, kind=connection.kind,
                     why=str(e))
        return None
    stored = await services.get(ConnectionResources).listed(connection.id, connection.household_id, found)
    logs.info(log, "connections.resources_listed", connection=connection.id, kind=connection.kind, count=len(stored))
    return stored
