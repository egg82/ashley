"""Which key each keyed model provider uses now (`decisions.md`, "A model provider's key is a connection").

The keys belong to the deployment, not a household: inference is one service for every household, so its keys are the
`FIRST_HOUSEHOLD`'s connections of the `deployment` kinds implementing the `inference` port, and the env's keys
(`ANTHROPIC_API_KEY` and the rest) stand in wherever that household has no row. A row always wins over the env: once
a key is stored, a changed env key is ignored until the row is removed."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD


@dataclass(frozen=True)
class KeyInForce:
    """The key a provider kind uses now: `secret`, left out of `repr`, from the connection `connection_id`, or from the
    env when that is None."""

    kind: str
    secret: str = field(repr=False)
    connection_id: int | None


class KeysUnavailable(Exception):
    """The stored keys could not be read now: the database is away, or a stored key does not open under this
    `CONNECTIONS_KEY`. Transient; the caller keeps the keys it last read."""


class ProviderKeys(ABC):
    @abstractmethod
    async def in_force(self) -> Mapping[str, KeyInForce]:
        """The key in force for each provider kind that has one, by kind name. Raises KeysUnavailable."""


class ConnectionProviderKeys(ProviderKeys):
    """The keys of `kinds` (provider kind names) from the connections, with `env` (kind name to the env's key, empty
    when unset) where there is no row.

    - With no `CONNECTIONS_KEY` (`Connections.can_open` false): the env's non-empty keys; never raises.
    - Otherwise each kind's key is the secret of `FIRST_HOUSEHOLD`'s household-held connection of that kind when one
      exists, else the env's when non-empty, else the kind is absent. Rows of kinds not in `kinds`, a person's own rows
      and other households' rows are never read. A database that cannot be reached, or a stored key that does not open,
      raises KeysUnavailable rather than answering with the env's keys, which a stored row may have replaced.

    `connections` is called on each read, so it follows the service the locator holds then. Reads only; logs nothing
    (the caller logs what changed)."""

    def __init__(self, connections: Callable[[], Connections], kinds: Iterable[str], env: Mapping[str, str]) -> None:
        self._connections = connections
        self._kinds = tuple(kinds)
        self._env = dict(env)

    async def in_force(self) -> Mapping[str, KeyInForce]:
        keys = {kind: KeyInForce(kind, secret, None) for kind, secret in self._env.items()
                if secret and kind in self._kinds}
        connections = self._connections()
        if not connections.can_open():
            return keys
        try:
            stored = await ports.opened_all(connections, "inference", FIRST_HOUSEHOLD)
        except ConnectionsUnavailable as e:
            raise KeysUnavailable("the stored keys could not be read") from e
        rows: set[str] = set()
        for opened in stored:
            kind = opened.connection.kind
            if kind in self._kinds and kind not in rows:
                rows.add(kind)
                keys[kind] = KeyInForce(kind, opened.secret, opened.connection.id)
        return keys
