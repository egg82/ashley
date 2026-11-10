"""An object store in memory: the stand-in for tests, and for a process with no storage to reach. `down` makes every
call raise StoreUnavailable, as a store that cannot be reached does."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from .store import ObjectStore, StoreUnavailable


class MemoryStore(ObjectStore):
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.objects: dict[str, bytes] = {}
        self.written: dict[str, datetime] = {}
        self.down = False
        self._clock = clock

    async def put(self, key: str, data: bytes) -> int:
        self._reach()
        self.objects[key] = data
        self.written[key] = self._clock()
        return 1

    async def get(self, key: str) -> bytes | None:
        self._reach()
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self._reach()
        self.objects.pop(key, None)
        self.written.pop(key, None)

    async def listing(self, prefix: str) -> Mapping[str, datetime]:
        self._reach()
        return {k: self.written.get(k, self._clock()) for k in self.objects if k.startswith(prefix)}

    def _reach(self) -> None:
        if self.down:
            raise StoreUnavailable("this store is down")
