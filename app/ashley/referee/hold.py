"""The maintenance switch for fail-back: while a hold is set, the fail-back singleton leaves the primary where it is.
One key in the referee's etcd, so one switch covers both sites; it lives under an etcd lease, so a forgotten hold
expires on its own. Failover is never held: Patroni still promotes the standby when the preferred site goes."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

from .etcd_gateway import Connect, EtcdClient, EtcdGateway, EtcdTls, EtcdUnavailable

HOLD_KEY = "/ashley/fail-back/hold"


class Hold(ABC):
    @abstractmethod
    async def held(self) -> bool:
        """Whether a hold is set. True when that cannot be read: unsure, the primary stays put."""


class EtcdHold(Hold):
    """The hold as `key` in etcd. Its value is the moment the hold expires (ISO 8601, UTC); the key goes with its
    lease at that moment. `connect` opens the etcd client, by default the JSON gateway at `url`."""

    def __init__(self, url: str, tls: EtcdTls | None = None, key: str = HOLD_KEY, timeout: float = 5.0,
                 connect: Connect | None = None) -> None:
        self._connect = connect or EtcdGateway.connect(url, tls)
        self._key = key
        self._timeout = timeout

    async def held(self) -> bool:
        try:
            return await self.until() is not None
        except EtcdUnavailable:
            return True

    async def until(self) -> datetime | None:
        """When the current hold expires, None when there is none. Raises `EtcdUnavailable`."""
        async with self._etcd() as etcd:
            value = await etcd.get(self._key)
        return None if value is None else datetime.fromisoformat(value)

    async def set(self, duration: timedelta) -> datetime:
        """Set or replace the hold for `duration` (whole seconds, at least one); when it expires. Raises
        `EtcdUnavailable`."""
        seconds = max(1, int(duration.total_seconds()))
        async with self._etcd() as etcd:
            grant = await etcd.grant(seconds)
            until = datetime.now(UTC) + timedelta(seconds=grant.ttl)
            await etcd.put(self._key, until.isoformat(), grant.lease_id)
        return until

    async def release(self) -> bool:
        """Clear the hold; whether there was one. Raises `EtcdUnavailable`."""
        async with self._etcd() as etcd:
            return await etcd.delete(self._key)

    def _etcd(self) -> EtcdClient:
        return self._connect(self._timeout)
