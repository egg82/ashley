"""`SourcedBalances`: the ProviderBalances service over a `BalanceSource` per provider, each read cached for `ttl` while
the provider's source stays the same object (a rotated key brings a new one, read afresh). Logs `balance.read`
(provider, outcome, ms) once per read that reaches the provider; never a key or an amount."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta

from .. import logs
from .balance import BalanceFailed, BalanceSource, ProviderBalances, Reading

log = logging.getLogger("ashley.inference")
TTL = timedelta(seconds=60)

Sources = Callable[[], Awaitable[Mapping[str, BalanceSource]]]
"""The balance sources wired now, by provider name (`KeyedProviders.balance_sources`)."""


def fixed(sources: Mapping[str, BalanceSource]) -> Sources:
    """`Sources` that are always `sources`."""
    async def current() -> Mapping[str, BalanceSource]:
        return sources
    return current


class SourcedBalances(ProviderBalances):
    def __init__(self, sources: Sources, now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 ttl: timedelta = TTL) -> None:
        self._sources = sources
        self._now = now
        self._ttl = ttl
        self._kept: dict[str, tuple[BalanceSource, Reading]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def reading(self, provider: str) -> Reading | None:
        source = (await self._sources()).get(provider)
        if source is None:
            return None
        async with self._locks.setdefault(provider, asyncio.Lock()):
            kept = self._kept.get(provider)
            if kept is not None and kept[0] is source and self._now() - kept[1].read_at < self._ttl:
                return kept[1]
            fresh = await self._read(provider, source)
            self._kept[provider] = (source, fresh)
            return fresh

    async def _read(self, provider: str, source: BalanceSource) -> Reading:
        started = time.monotonic()
        try:
            quota = await source.read()
            outcome = "ok"
        except BalanceFailed as failed:
            quota, outcome = None, failed.outcome
        logs.info(log, "balance.read", provider=provider, outcome=outcome, ms=round((time.monotonic() - started) * 1000))
        return Reading(self._now(), quota)
