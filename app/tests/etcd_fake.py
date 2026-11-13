"""A second etcd behind `EtcdClient`: in memory, keeping time by the running loop's clock, so on `virtual_time`'s loop
a lease's TTL passes the moment nothing else is ready. `contract/test_contract_etcd_client.py` holds it to the real
etcd. A lease expires exactly when its TTL runs out; the real one may keep it a moment longer, never less."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from ashley.referee.etcd_gateway import Connect, EtcdClient, EtcdUnavailable, Grant

MIN_TTL = 2
"""The shortest lease etcd grants with its default timings (3/2 of a 1 s election timeout, rounded up)."""

LEASE_NOT_FOUND = 404


@dataclass
class Link:
    """One process's path to etcd. `down`: every call fails at once, as a refused connection does. `txn_delay`: a
    transaction is applied, then its answer takes that many seconds to arrive, and never does past the client's
    timeout. `before_txn` runs just before a transaction reaches etcd."""

    down: bool = False
    txn_delay: float = 0.0
    before_txn: Callable[[], None] | None = None


def _now() -> float:
    return asyncio.get_running_loop().time()


class FakeEtcd:
    """The server: keys with their values and leases, and leases with when each expires. The methods without a
    client are a test's own view and hand on it, as the real tests' raw HTTP calls are; they reach it over no link."""

    def __init__(self) -> None:
        self._kv: dict[str, tuple[str, int]] = {}
        self._leases: dict[int, tuple[int, float]] = {}
        self._next_id = 0x694D_0000_0000_0001

    def connect(self, link: Link | None = None) -> Connect:
        return lambda timeout: _Client(self, link or Link(), timeout)

    def _expire(self) -> None:
        if not self._leases:
            return
        now = _now()
        for lease_id, (_, expires) in list(self._leases.items()):
            if expires <= now:
                self._drop(lease_id)

    def _drop(self, lease_id: int) -> None:
        del self._leases[lease_id]
        for key in [k for k, (_, owner) in self._kv.items() if owner == lease_id]:
            del self._kv[key]

    def _live(self, lease_id: int) -> None:
        if lease_id and lease_id not in self._leases:
            raise EtcdUnavailable("status", LEASE_NOT_FOUND)

    def grant(self, ttl: int) -> Grant:
        self._expire()
        lease_id, self._next_id = self._next_id, self._next_id + 1
        granted = max(ttl, MIN_TTL)
        self._leases[lease_id] = (granted, _now() + granted)
        return Grant(lease_id, granted)

    def keepalive(self, lease_id: int) -> int:
        self._expire()
        if lease_id not in self._leases:
            return 0
        ttl, _ = self._leases[lease_id]
        self._leases[lease_id] = (ttl, _now() + ttl)
        return ttl

    def claim(self, key: str, value: str, lease_id: int, guard: tuple[str, str] | None) -> bool:
        self._expire()
        if key in self._kv or (guard is not None and self.value(guard[0]) != guard[1]):
            return False
        self._live(lease_id)
        self._kv[key] = (value, lease_id)
        return True

    def put(self, key: str, value: str, lease_id: int = 0) -> None:
        self._expire()
        self._live(lease_id)
        self._kv[key] = (value, lease_id)

    def delete(self, key: str) -> bool:
        self._expire()
        return self._kv.pop(key, None) is not None

    def prefix(self, prefix: str, exact: bool = False) -> dict[str, str]:
        self._expire()
        return {k: v for k, (v, _) in self._kv.items() if (k == prefix if exact else k.startswith(prefix))}

    def revoke(self, lease_id: int) -> None:
        self._expire()
        if lease_id in self._leases:
            self._drop(lease_id)

    def value(self, key: str) -> str | None:
        self._expire()
        entry = self._kv.get(key)
        return None if entry is None else entry[0]

    def lease_of(self, key: str) -> int | None:
        """The lease `key` lives under, None when the key is absent or under none."""
        self._expire()
        entry = self._kv.get(key)
        if entry is None or entry[1] == 0:
            return None
        return entry[1]


class _Client(EtcdClient):
    """Each call yields to the loop on the way out and on the way back, as a request and its answer do."""

    def __init__(self, etcd: FakeEtcd, link: Link, timeout: float) -> None:
        self._etcd = etcd
        self._link = link
        self._timeout = timeout

    async def _reach(self) -> None:
        if self._link.down:
            raise EtcdUnavailable("ConnectError")
        await asyncio.sleep(0)

    async def grant(self, ttl: int) -> Grant:
        await self._reach()
        grant = self._etcd.grant(ttl)
        await asyncio.sleep(0)
        return grant

    async def keepalive(self, lease_id: int) -> int:
        await self._reach()
        ttl = self._etcd.keepalive(lease_id)
        await asyncio.sleep(0)
        return ttl

    async def claim(self, key: str, value: str, lease_id: int, guard: tuple[str, str] | None) -> bool:
        await self._reach()
        if self._link.before_txn is not None:
            self._link.before_txn()
        done = self._etcd.claim(key, value, lease_id, guard)
        if self._link.txn_delay >= self._timeout:
            await asyncio.sleep(self._timeout)
            raise EtcdUnavailable("ReadTimeout")
        await asyncio.sleep(self._link.txn_delay)
        return done

    async def put(self, key: str, value: str, lease_id: int) -> None:
        await self._reach()
        self._etcd.put(key, value, lease_id)
        await asyncio.sleep(0)

    async def delete(self, key: str) -> bool:
        await self._reach()
        existed = self._etcd.delete(key)
        await asyncio.sleep(0)
        return existed

    async def prefix(self, prefix: str, exact: bool = False) -> dict[str, str]:
        await self._reach()
        found = self._etcd.prefix(prefix, exact)
        await asyncio.sleep(0)
        return found

    async def revoke(self, lease_id: int) -> None:
        await self._reach()
        self._etcd.revoke(lease_id)
        await asyncio.sleep(0)
