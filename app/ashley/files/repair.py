"""The repair singleton: every `repair_interval_s`, under the etcd lease, copy to each site's store what another holds
and it lacks under each of the given key prefixes (an upload made while a site was down). Wired whenever the store is a
connection's, and a pass does nothing while it names one site."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence

from .. import logs
from .connected_store import ConnectedStore
from .mirror import MirroredStore
from .store import StoreUnavailable

log = logging.getLogger("ashley.files")
NAME = "files-repair"


async def run_once(store: MirroredStore | ConnectedStore, prefixes: Sequence[str]) -> int:
    """One comparison of each prefix; returns the copies written, none while `store` is one site's. Logs
    `files.repaired` with the count and duration, and `files.repair_failed` when a store could not be listed or none is
    connected (nothing is copied then)."""
    started = time.monotonic()
    try:
        mirror = await store.current() if isinstance(store, ConnectedStore) else store
        if not isinstance(mirror, MirroredStore):
            return 0
        written = 0
        for prefix in prefixes:
            written += await mirror.repair(prefix)
    except StoreUnavailable as e:
        logs.warning(log, "files.repair_failed", error=type(e).__name__)
        return 0
    logs.info(log, "files.repaired", copies=written, ms=int((time.monotonic() - started) * 1000))
    return written


async def run(store: MirroredStore | ConnectedStore, prefixes: Sequence[str], interval_s: float, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Compare, wait, repeat, until cancelled."""
    while True:
        await run_once(store, prefixes)
        await sleep(interval_s)
