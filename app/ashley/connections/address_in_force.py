"""The address a deployment's service is reached at now (`decisions.md`, "Env var, file, connection or setting"): the
first household's connection of one kind when it has one, else the env's. For a caller that asks on each use, so a
connection added, replaced or removed in the room is seen on the next, with no restart."""

import logging
from collections.abc import Callable

from .. import logs
from .connections import Connections, ConnectionsUnavailable
from .kinds import FIRST_HOUSEHOLD

log = logging.getLogger("ashley.connections")


class AddressInForce:
    """`kind` names the connection kind; `env` is the env's address, empty when unset. Calling it gives the address of
    `FIRST_HOUSEHOLD`'s household-held connection of `kind`; the env's when there is none, when no `CONNECTIONS_KEY` is
    set or when the connections cannot be read (logged `connections.address_unreadable` with the kind); empty when
    there is neither. Reads the address only, never the secret. `connections` is called on each read, so it follows the
    service the locator holds then."""

    def __init__(self, connections: Callable[[], Connections], kind: str, env: str) -> None:
        self._connections = connections
        self._kind = kind
        self._env = env

    async def __call__(self) -> str:
        connections = self._connections()
        if not connections.can_open():
            return self._env
        try:
            held = await connections.of_household(FIRST_HOUSEHOLD)
        except ConnectionsUnavailable:
            logs.warning(log, "connections.address_unreadable", kind=self._kind)
            return self._env
        return next((c.base_url for c in held if c.kind == self._kind and c.person_id is None), self._env)
