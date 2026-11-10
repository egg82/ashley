"""`SourcedBalances`: the ProviderBalances service over a `BalanceSource` per provider, each read cached for `ttl`.
Logs `balance.read` (provider, outcome, ms) once per read that reaches the provider; never a key or an amount."""

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from .. import logs
from .balance import BalanceFailed, BalanceSource, ProviderBalances, Reading

log = logging.getLogger("ashley.inference")
TTL = timedelta(seconds=60)


class SourcedBalances(ProviderBalances):
    def __init__(self, sources: Mapping[str, BalanceSource], now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 ttl: timedelta = TTL) -> None:
        self._sources = dict(sources)
        self._now = now
        self._ttl = ttl
        self._kept: dict[str, Reading] = {}
        self._locks = {name: asyncio.Lock() for name in sources}

    async def reading(self, provider: str) -> Reading | None:
        source = self._sources.get(provider)
        if source is None:
            return None
        async with self._locks[provider]:
            kept = self._kept.get(provider)
            if kept is not None and self._now() - kept.read_at < self._ttl:
                return kept
            fresh = await self._read(provider, source)
            self._kept[provider] = fresh
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
