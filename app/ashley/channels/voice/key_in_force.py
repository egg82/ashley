"""The Noise key a household's satellites are reached with now (`decisions.md`, "Env var, file, connection or
setting"): the household's own satellites connection when it holds one; for `FIRST_HOUSEHOLD` alone, the env's key
otherwise, since the env describes that household. Asked on each connect, so a key replaced in the room is used by the
next connection of each satellite."""

from collections.abc import Callable

from ...connections.connections import Connections, ConnectionsUnavailable
from ...connections.kinds import FIRST_HOUSEHOLD
from .key_kind import NAME


class NoKey(OSError):
    """No key is in force for the household: none held, or the held one could not be opened."""


class KeyInForce:
    """`env` is the env's key, empty when unset. `connections` is called on each read, so it follows the service the
    locator holds then. Calling it with a household gives that household's key. Raises NoKey when there is none, and
    when the rows cannot be read or the stored key does not open, rather than answering with an env key a row may have
    replaced."""

    def __init__(self, connections: Callable[[], Connections], env: str) -> None:
        self._connections = connections
        self._env = env

    async def __call__(self, household_id: int) -> str:
        env = self._env if household_id == FIRST_HOUSEHOLD else ""
        connections = self._connections()
        if not connections.can_open():
            return self._found(env)
        try:
            held = await connections.of_household(household_id)
            row = next((c for c in held if c.kind == NAME and c.person_id is None), None)
            opened = None if row is None else await connections.opened(row.id, household_id)
        except ConnectionsUnavailable:
            raise NoKey("satellite keys cannot be read") from None
        return self._found(env if opened is None else opened.secret)

    @staticmethod
    def _found(key: str) -> str:
        if not key:
            raise NoKey("no satellite key is set")
        return key
