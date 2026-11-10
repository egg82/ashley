"""Several stores as one, each a site's copy: a write goes to every store at once and counts when one took it, a read
asks the stores in order (the local site's first) and takes the first that has it, and `repair` copies what one site
holds and another lacks. Losing a site loses no file and stops no upload."""

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime

from .. import logs
from .store import ObjectStore, StoreUnavailable

log = logging.getLogger("ashley.files")


class MirroredStore(ObjectStore):
    def __init__(self, stores: list[ObjectStore]) -> None:
        if not stores:
            raise ValueError("a mirrored store needs at least one store")
        self._stores = stores

    @property
    def stores(self) -> tuple[ObjectStore, ...]:
        """Each site's store, the local site's first."""
        return tuple(self._stores)

    async def put(self, key: str, data: bytes) -> int:
        """Raises StoreUnavailable when no store took it; a store that did not logs `files.copy_failed`."""
        results = await asyncio.gather(*(s.put(key, data) for s in self._stores), return_exceptions=True)
        copies = sum(1 for r in results if not isinstance(r, BaseException))
        for index, r in enumerate(results):
            if isinstance(r, BaseException):
                logs.warning(log, "files.copy_failed", store=index, error=type(r).__name__)
        if copies == 0:
            raise StoreUnavailable("no store took the write")
        return copies

    async def get(self, key: str) -> bytes | None:
        """Raises StoreUnavailable when no store answered; a store that failed is skipped for the next."""
        answered = False
        for index, store in enumerate(self._stores):
            try:
                found = await store.get(key)
            except StoreUnavailable as e:
                logs.warning(log, "files.read_failed", store=index, error=type(e).__name__)
                continue
            answered = True
            if found is not None:
                return found
        if not answered:
            raise StoreUnavailable("no store answered")
        return None

    async def delete(self, key: str) -> None:
        """Remove `key` from every store. Raises StoreUnavailable when none took the delete; a store that did not
        logs `files.delete_failed`."""
        results = await asyncio.gather(*(s.delete(key) for s in self._stores), return_exceptions=True)
        for index, r in enumerate(results):
            if isinstance(r, BaseException):
                logs.warning(log, "files.delete_failed", store=index, error=type(r).__name__)
        if all(isinstance(r, BaseException) for r in results):
            raise StoreUnavailable("no store took the delete")

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        """The union of what every store that answered holds, each key at its newest write. Raises StoreUnavailable
        when none answered."""
        results = await asyncio.gather(*(s.listing(prefix) for s in self._stores), return_exceptions=True)
        held: list[Mapping[str, datetime]] = [r for r in results if not isinstance(r, BaseException)]
        if not held:
            raise StoreUnavailable("no store answered")
        newest: dict[str, datetime] = {}
        for found in held:
            for key, at in found.items():
                newest[key] = max(at, newest.get(key, at))
        return newest

    async def repair(self, prefix: str) -> int:
        """Copy to each store the keys under `prefix` that it lacks and another holds; returns how many copies it
        wrote. Raises StoreUnavailable when a store cannot be listed, since a store not listed would look empty."""
        held = await asyncio.gather(*(s.keys(prefix) for s in self._stores))
        wanted = frozenset(key for keys in held for key in keys)
        written = 0
        for store, have in zip(self._stores, held):
            for key in sorted(wanted - have):
                data = await self.get(key)
                if data is not None:
                    await store.put(key, data)
                    written += 1
        return written
