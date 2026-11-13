"""The catalogue's second layer kept fresh: under the lease `model-catalogue`, fetch models.dev's list once the stored
fetch is `refresh_s` old (`catalogue.json`) and store it whole. A fetch that fails, or a list that does not read, keeps
the stored one; the next try is `retry_s` later, as after a failed read of the stored fetch. A pod taking the lease
fetches at once only when the stored fetch is already due, so a failover does not fetch twice.

Logs `catalogue.fetched` (providers, models, skipped, duration_ms) and `catalogue.fetch_failed` (reason: the error's
kind or the HTTP status), and `catalogue.store_unavailable` once per run of failed reads of the stored fetch."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx2

from .. import logs
from . import models_dev
from .catalogue import ModelCatalogueUnavailable
from .catalogue_config import CatalogueConfig
from .catalogue_store import CatalogueStore

log = logging.getLogger("ashley.inference")
NAME = "model-catalogue"

Fetch = Callable[[], Awaitable[models_dev.Read]]


def utc_now() -> datetime:
    return datetime.now(UTC)


async def refresh_once(store: CatalogueStore, fetch: Fetch, now: datetime,
                       clock: Callable[[], float] = time.monotonic) -> bool:
    """Fetch and store the list; True when it was stored. Never raises but ModelCatalogueUnavailable from the store."""
    started = clock()
    try:
        read = await fetch()
    except httpx2.HTTPStatusError as e:
        logs.warning(log, "catalogue.fetch_failed", reason=f"status_{e.response.status_code}")
        return False
    except (httpx2.HTTPError, ValueError) as e:
        logs.warning(log, "catalogue.fetch_failed", reason=type(e).__name__)
        return False
    await store.put_fetch(read.catalogue, now)
    logs.info(log, "catalogue.fetched", providers=len(read.catalogue.providers), models=read.catalogue.model_count(),
              skipped=read.skipped, duration_ms=max(0, round((clock() - started) * 1000)))
    return True


async def run(config: CatalogueConfig, store: CatalogueStore, fetch: Fetch,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
              now: Callable[[], datetime] = utc_now) -> None:
    """Refresh whenever the stored fetch is due, until cancelled."""
    failing = False
    while True:
        wait = config.refresh_s
        try:
            fetched_at = await store.fetched_at()
            age = None if fetched_at is None else (now() - fetched_at).total_seconds()
            if age is None or age >= config.refresh_s:
                if not await refresh_once(store, fetch, now()):
                    wait = config.retry_s
            else:
                wait = config.refresh_s - age
            failing = False
        except ModelCatalogueUnavailable:
            if not failing:
                logs.warning(log, "catalogue.store_unavailable")
            failing = True
            wait = config.retry_s
        await sleep(wait)
