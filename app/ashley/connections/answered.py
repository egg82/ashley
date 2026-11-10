"""Recording that a service answered with a connection: the one place an adapter calls after a successful read."""

import logging

from .. import logs, services
from .connections import Connections, ConnectionsUnavailable

log = logging.getLogger("ashley.connections")


async def record(connection_id: int) -> None:
    """Move the connection's `checked_at` to now. A connection that cannot be written is logged
    `connections.answered_unrecorded` and the read it follows is unaffected."""
    try:
        await services.get(Connections).answered(connection_id)
    except ConnectionsUnavailable:
        logs.warning(log, "connections.answered_unrecorded", connection=connection_id)
