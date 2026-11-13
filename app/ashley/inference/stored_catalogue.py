"""The ModelCatalogue implementation: the image's snapshot, and the stored fetch and overrides read again by the first
call once the last read is `REFRESH_S` old. Contract: `catalogue.ModelCatalogue`.

Each pod keeps a cache, not state: an override set or a fetch stored on any pod reaches every pod's pricing within
that bound. The fetch is read again only when its time has changed. A read that fails keeps what was built (logged
`catalogue.unreadable`); before any succeeds, calls are priced from the snapshot alone."""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime

from .. import logs
from .catalogue import CatalogueState, ModelCatalogueUnavailable, ModelCatalogue, PricedCatalogue
from .catalogue_config import CatalogueConfig
from .catalogue_merge import Override, merged, upstream
from .catalogue_model import Catalogue
from .catalogue_store import CatalogueStore

log = logging.getLogger("ashley.inference")

REFRESH_S = 30.0
"""How old the stored layers read last may be before a call reads them again."""


class StoredCatalogue(ModelCatalogue):
    def __init__(self, snapshot: tuple[Catalogue, datetime] | None, store: CatalogueStore, config: CatalogueConfig,
                 clock: Callable[[], float] = time.monotonic, refresh_s: float = REFRESH_S) -> None:
        self._snapshot = snapshot
        self._store = store
        self._config = config
        self._clock = clock
        self._refresh_s = refresh_s
        self._lock = asyncio.Lock()
        self._read_at: float | None = None
        self._fetched: tuple[Catalogue, datetime] | None = None
        self._overrides: list[Override] = []
        self._priced = self._build()

    def priced(self) -> PricedCatalogue:
        return self._priced

    async def refresh(self) -> None:
        if not self._due():
            return
        async with self._lock:
            if not self._due():
                return
            self._read_at = self._clock()
            try:
                await self._read()
            except ModelCatalogueUnavailable:
                logs.warning(log, "catalogue.unreadable")
            except Exception:
                logs.error(log, "catalogue.unreadable", exc=True)

    async def state(self) -> CatalogueState:
        async with self._lock:
            await self._read()
            self._read_at = self._clock()
        return CatalogueState(self._priced.merged, None if self._snapshot is None else self._snapshot[1],
                              None if self._fetched is None else self._fetched[1])

    def _due(self) -> bool:
        return self._read_at is None or self._clock() - self._read_at >= self._refresh_s

    async def _read(self) -> None:
        at = await self._store.fetched_at()
        fetched = self._fetched
        if at is None:
            fetched = None
        elif fetched is None or fetched[1] != at:
            fetched = await self._store.fetched()
        overrides = await self._store.overrides()
        if fetched is self._fetched and overrides == self._overrides:
            return
        self._fetched, self._overrides = fetched, overrides
        self._priced = self._build()

    def _build(self) -> PricedCatalogue:
        catalogue, layer = upstream(None if self._snapshot is None else self._snapshot[0],
                                    None if self._fetched is None else self._fetched[0])
        return PricedCatalogue(merged(catalogue, layer, self._overrides), self._config)
