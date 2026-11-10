"""The repair singleton: every `repair_interval_s`, under the etcd lease, copy to each site's store what another holds
and it lacks under each of the given key prefixes (an upload made while a site was down). Wired only when more than one
store is."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from .. import logs
from .mirror import MirroredStore
from .store import StoreUnavailable

log = logging.getLogger("ashley.files")
NAME = "files-repair"


async def run_once(store: MirroredStore, prefixes: Sequence[str]) -> int:
    """One comparison of each prefix; returns the copies written. Logs `files.repaired` with the count and duration, and
    `files.repair_failed` when a store could not be listed (nothing is copied then)."""
    started = time.monotonic()
    try:
        written = 0
        for prefix in prefixes:
            written += await store.repair(prefix)
    except StoreUnavailable as e:
        logs.warning(log, "files.repair_failed", error=type(e).__name__)
        return 0
    logs.info(log, "files.repaired", copies=written, ms=int((time.monotonic() - started) * 1000))
    return written


async def run(store: MirroredStore, prefixes: Sequence[str], interval_s: float, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Compare, wait, repeat, until cancelled."""
    while True:
        await run_once(store, prefixes)
        await sleep(interval_s)
