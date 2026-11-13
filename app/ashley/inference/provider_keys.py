"""Which key each keyed model provider uses now (`decisions.md`, "A model provider's key is a connection").

The keys belong to the deployment, not a household: inference is one service for every household, so its keys are the
`FIRST_HOUSEHOLD`'s connections of the `deployment` kinds implementing the `inference` port, and the env's keys
(`ANTHROPIC_API_KEY` and the rest) stand in wherever that household has no row. A row always wins over the env: once
a key is stored, a changed env key is ignored until the row is removed.

An OpenAI-compatible provider (`ashley.inference.compatible`) is one of many connections of one kind, so its key is
read per connection, by label, beside its address and the catalogue provider its calls are priced as."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD


@dataclass(frozen=True)
class KeyInForce:
    """The key a provider kind uses now: `secret`, left out of `repr`, from the connection `connection_id`, or from the
    env when that is None. For an OpenAI-compatible provider, also the `label` routes name it by, the `base_url` it is
    reached at and the `catalogue_provider` its calls are priced as (None: unpriced); empty for the keyed kinds, which
    have one address each."""

    kind: str
    secret: str = field(repr=False)
    connection_id: int | None
    base_url: str = ""
    label: str = ""
    catalogue_provider: str | None = None


class KeysUnavailable(Exception):
    """The stored keys could not be read now: the database is away, or a stored key does not open under this
    `CONNECTIONS_KEY`. Transient; the caller keeps the keys it last read."""


class ProviderKeys(ABC):
    @abstractmethod
    async def in_force(self) -> Mapping[str, KeyInForce]:
        """The key in force for each provider kind that has one, by kind name, and for each OpenAI-compatible provider,
        by its label. Raises KeysUnavailable."""


class ConnectionProviderKeys(ProviderKeys):
    """The keys of `kinds` (provider kind names) from the connections, with `env` (kind name to the env's key, empty
    when unset) where there is no row.

    - With no `CONNECTIONS_KEY` (`Connections.can_open` false): the env's non-empty keys; never raises.
    - Otherwise each kind's key is the secret of `FIRST_HOUSEHOLD`'s household-held connection of that kind when one
      exists, else the env's when non-empty, else the kind is absent. Rows of kinds not in `kinds`, a person's own rows
      and other households' rows are never read. A database that cannot be reached, or a stored key that does not open,
      raises KeysUnavailable rather than answering with the env's keys, which a stored row may have replaced.

    `compatible` names the OpenAI-compatible kind: each `FIRST_HOUSEHOLD` connection of it is in force under its
    label, and `compatible_env` (label to key, the env's local server) stands in for a label no row has, as `env` does
    for a kind.

    `addressed` are the kinds reached at an address and no key (Wyoming): the first household's household-held connection
    of each is in force under the kind's name, with its `base_url` and an empty secret, and `addressed_env` (kind name
    to the env's address) stands in where there is no row.

    `connections` is called on each read, so it follows the service the locator holds then. Reads only; logs nothing
    (the caller logs what changed)."""

    def __init__(self, connections: Callable[[], Connections], kinds: Iterable[str], env: Mapping[str, str],
                 compatible: str | None = None, compatible_env: Mapping[str, KeyInForce] | None = None,
                 addressed: Iterable[str] = (), addressed_env: Mapping[str, str] | None = None) -> None:
        self._connections = connections
        self._kinds = tuple(kinds)
        self._env = dict(env)
        self._compatible = compatible
        self._compatible_env = dict(compatible_env or {})
        self._addressed = tuple(addressed)
        self._addressed_env = dict(addressed_env or {})

    async def in_force(self) -> Mapping[str, KeyInForce]:
        keys = {kind: KeyInForce(kind, secret, None) for kind, secret in self._env.items()
                if secret and kind in self._kinds}
        keys.update(self._compatible_env)
        keys.update({kind: KeyInForce(kind, "", None, address) for kind, address in self._addressed_env.items()
                     if address and kind in self._addressed})
        connections = self._connections()
        if not connections.can_open():
            return keys
        try:
            stored = await ports.opened_all(connections, "inference", FIRST_HOUSEHOLD)
        except ConnectionsUnavailable as e:
            raise KeysUnavailable("the stored keys could not be read") from e
        rows: set[str] = set()
        for opened in stored:
            c = opened.connection
            if c.kind == self._compatible:
                keys[c.label] = KeyInForce(c.kind, opened.secret, c.id, c.base_url, c.label, c.catalogue_provider)
            elif c.kind in self._addressed and c.kind not in rows:
                rows.add(c.kind)
                keys[c.kind] = KeyInForce(c.kind, "", c.id, c.base_url)
            elif c.kind in self._kinds and c.kind not in rows:
                rows.add(c.kind)
                keys[c.kind] = KeyInForce(c.kind, opened.secret, c.id)
        return keys
