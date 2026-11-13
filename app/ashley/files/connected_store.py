"""The object store the deployment's connection names, or the env's when there is none (`decisions.md`, "Env var, file,
connection or setting"). Each pod keeps a cache, not state: the store built from the first household's `files`
connection, read again by the first call once the last read is `REFRESH_S` old, so a connection added, replaced or
removed in the room reaches every pod within that bound with no restart."""

import logging
import time
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx2

from .. import logs
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD
from .mirror import MirroredStore
from .s3 import S3Store
from .store import ObjectStore, StoreUnavailable
from .store_kind import NAME, Keys, keys_of

log = logging.getLogger("ashley.files")

REFRESH_S = 30.0


def built(keys: Keys, http: httpx2.AsyncClient) -> ObjectStore:
    """The store over every endpoint in `keys`: the one store for a single endpoint, otherwise every site's as a
    `MirroredStore`, in the order given."""
    stores: list[ObjectStore] = [S3Store(endpoint.strip(), keys.bucket, keys.access_key, keys.secret_key, http)
                                 for endpoint in keys.endpoints.split(",") if endpoint.strip()]
    return stores[0] if len(stores) == 1 else MirroredStore(stores)


class ConnectedStore(ObjectStore):
    """`env` is the env's store, None when unset; `connections` is called on each read, so it follows the service the
    locator holds then; `http` sends every store's requests. A row wins over the env; with neither, every call raises
    StoreUnavailable. A read that fails (`files.store_unreadable`) keeps what was wired and is tried again after the
    same bound; before the first read succeeds the env's store is wired. Logs `files.store_changed` with `to`:
    `connection`, `env` or `none`, never an address or key."""

    def __init__(self, connections: Callable[[], Connections], env: Keys | None, http: httpx2.AsyncClient,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._connections = connections
        self._env = env
        self._http = http
        self._clock = clock
        self._keys: Keys | None = env
        self._store: ObjectStore | None = None if env is None else built(env, http)
        self._read_at: float | None = None

    async def current(self) -> ObjectStore:
        """The store in force now. Raises StoreUnavailable when there is none."""
        if self._read_at is None or self._clock() - self._read_at >= REFRESH_S:
            await self._refresh()
        if self._store is None:
            raise StoreUnavailable("no object store is connected")
        return self._store

    async def put(self, key: str, data: bytes) -> int:
        return await (await self.current()).put(key, data)

    async def get(self, key: str) -> bytes | None:
        return await (await self.current()).get(key)

    async def delete(self, key: str) -> None:
        await (await self.current()).delete(key)

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        return await (await self.current()).listing(prefix)

    async def _refresh(self) -> None:
        self._read_at = self._clock()
        connections = self._connections()
        if not connections.can_open():
            return
        try:
            row = await self._row(connections)
        except ConnectionsUnavailable:
            logs.warning(log, "files.store_unreadable")
            return
        wanted = self._env if row is None else row
        if wanted != self._keys:
            self._keys = wanted
            self._store = None if wanted is None else built(wanted, self._http)
            logs.info(log, "files.store_changed", to="none" if wanted is None else "env" if row is None else "connection")

    async def _row(self, connections: Connections) -> Keys | None:
        """The first household's store connection as keys; None when it has none or its secret does not open or is not
        the shape `store_kind.Keys.secret` writes (logged `files.store_row_unusable`). Raises ConnectionsUnavailable."""
        held = await connections.of_household(FIRST_HOUSEHOLD)
        row = next((c for c in held if c.kind == NAME and c.person_id is None), None)
        if row is None:
            return None
        opened = await connections.opened(row.id, FIRST_HOUSEHOLD)
        keys = None if opened is None else keys_of(row.base_url, opened.secret)
        if keys is None:
            logs.warning(log, "files.store_row_unusable")
        return keys
