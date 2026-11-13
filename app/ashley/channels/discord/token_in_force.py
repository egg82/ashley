"""Which token her Discord bot uses now (`decisions.md`, "Env var, file, connection or setting"): the first household's
household-held Discord connection when it has one, else the env's. A row always wins; for a caller that asks on each
use, so a token replaced or removed in the room is seen on the next read."""

from collections.abc import Callable

from ...connections.connections import Connections
from ...connections.kinds import FIRST_HOUSEHOLD
from .token_kind import NAME


class TokenInForce:
    """`env` is the env's token, empty when unset. Calling it gives the stored token of `FIRST_HOUSEHOLD`'s
    household-held Discord connection; the env's when there is none or when no `CONNECTIONS_KEY` is set; empty when
    there is neither. Raises ConnectionsUnavailable when the rows cannot be read or the stored token does not open,
    rather than answering with an env token the row may have replaced. `connections` is called on each read, so it
    follows the service the locator holds then."""

    def __init__(self, connections: Callable[[], Connections], env: str) -> None:
        self._connections = connections
        self._env = env

    async def __call__(self) -> str:
        connections = self._connections()
        if not connections.can_open():
            return self._env
        held = await connections.of_household(FIRST_HOUSEHOLD)
        row = next((c for c in held if c.kind == NAME and c.person_id is None), None)
        if row is None:
            return self._env
        opened = await connections.opened(row.id, FIRST_HOUSEHOLD)
        return self._env if opened is None else opened.secret
