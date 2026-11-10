"""The object store (`ashley.services`): bytes kept under a key, outside Postgres, for what is too large to be a row
(a bench's uploaded files). The interface is neutral: a key is `/`-separated text, a value is bytes, and what holds
them (S3-compatible storage on each site's NAS, memory in a test) is the adapter's alone. Callers import this module
and ask the locator; keys and bytes are people's data and are never logged."""

from abc import abstractmethod
from collections.abc import Mapping
from datetime import datetime

from ..services import Service


class StoreUnavailable(Exception):
    """The bytes could not be written or read: no store is wired, or none that holds them could be reached.
    Nothing is known to have changed. Transient."""


class ObjectStore(Service):
    @classmethod
    def null(cls) -> "ObjectStore":
        return NullStore()

    @abstractmethod
    async def put(self, key: str, data: bytes) -> int:
        """Keep `data` under `key`, replacing what was there, and return how many copies now hold it (at least 1).
        Raises StoreUnavailable when no copy was written."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """The bytes under `key`, None when no copy holds any. Raises StoreUnavailable when none could be asked."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the bytes under `key`; a key nothing holds is not an error. Raises StoreUnavailable."""

    @abstractmethod
    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        """Every key that starts with `prefix`, each with when its bytes were last written (timezone-aware).
        Raises StoreUnavailable."""

    async def keys(self, prefix: str) -> frozenset[str]:
        """Every key that starts with `prefix`. Raises StoreUnavailable."""
        return frozenset(await self.listing(prefix))


class NullStore(ObjectStore):
    """What an unwired process sees: every call raises StoreUnavailable."""

    async def put(self, key: str, data: bytes) -> int:
        raise StoreUnavailable("no object store is wired")

    async def get(self, key: str) -> bytes | None:
        raise StoreUnavailable("no object store is wired")

    async def delete(self, key: str) -> None:
        raise StoreUnavailable("no object store is wired")

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        raise StoreUnavailable("no object store is wired")
