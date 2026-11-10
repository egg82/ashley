"""The sweep singleton: every `sweep_interval_s`, under the etcd lease, delete from each site's store (the one store, when there is one site) the bytes no piece
names. The store is listed first and the references read after, so a piece committed during the pass is seen.

A key is deleted only when it is unreferenced, was last written at least `sweep_grace_s` ago on every site that holds
it (an upload in flight is younger), and the pass before found it unreferenced and old enough too (`Candidates`, kept in
Postgres since the next pass may run on another pod). A site that cannot be listed or deleted from is skipped for the
pass and the others go on. Keys and bytes are people's data: logs carry only counts."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .. import logs
from .config import FilesConfig
from .intake import PREFIX
from .mirror import MirroredStore
from .store import ObjectStore, StoreUnavailable

log = logging.getLogger("ashley.files")
NAME = "files-sweep"
Referenced = Callable[[], Awaitable[frozenset[str]]]


class Candidates(Protocol):
    async def load(self) -> frozenset[str]:
        """The keys the previous pass found unreferenced and old enough."""
        ...

    async def save(self, keys: frozenset[str]) -> None:
        """Make `keys` the candidates for the next pass."""
        ...


@dataclass(frozen=True)
class Swept:
    """What one pass found: keys listed (across sites), unreferenced, and copies deleted (one per site)."""

    seen: int
    unreferenced: int
    deleted: int


def _sites(store: ObjectStore) -> tuple[ObjectStore, ...]:
    """The stores one pass visits: each site's of a mirror, otherwise the store itself."""
    return store.stores if isinstance(store, MirroredStore) else (store,)


async def _listed(stores: tuple[ObjectStore, ...]) -> dict[int, Mapping[str, datetime]]:
    """Each site's listing; a site that cannot be listed is logged and left out."""
    found: dict[int, Mapping[str, datetime]] = {}
    for index, store in enumerate(stores):
        try:
            found[index] = await store.listing(PREFIX)
        except StoreUnavailable:
            logs.error(log, "files.sweep_list_failed", exc=True, store=index)
    return found


def _newest(listings: Mapping[int, Mapping[str, datetime]]) -> dict[str, datetime]:
    newest: dict[str, datetime] = {}
    for found in listings.values():
        for key, at in found.items():
            newest[key] = max(at, newest.get(key, at))
    return newest


def _old_unreferenced(newest: Mapping[str, datetime], named: frozenset[str], cutoff: datetime) -> frozenset[str]:
    return frozenset(key for key, at in newest.items() if key not in named and at <= cutoff)


async def _delete_from(index: int, store: ObjectStore, keys: list[str]) -> frozenset[str]:
    """The keys deleted from one site; it stops at the first failure, which is logged."""
    done: set[str] = set()
    for key in keys:
        try:
            await store.delete(key)
        except StoreUnavailable:
            logs.error(log, "files.sweep_delete_failed", exc=True, store=index)
            break
        done.add(key)
    return frozenset(done)


async def _pass(store: ObjectStore, referenced: Referenced, candidates: Candidates, config: FilesConfig,
                now: datetime) -> Swept | None:
    stores = _sites(store)
    listings = await _listed(stores)
    if not listings:
        return None
    named = await referenced()
    newest = _newest(listings)
    eligible = _old_unreferenced(newest, named, now - timedelta(seconds=config.sweep_grace_s))
    condemned = eligible & await candidates.load()
    survivors = set(eligible - condemned)
    deleted = 0
    for index, found in sorted(listings.items()):
        started = time.monotonic()
        gone = await _delete_from(index, stores[index], sorted(condemned & found.keys()))
        deleted += len(gone)
        survivors |= condemned & found.keys() - gone
        logs.info(log, "files.sweep_store", store=index, seen=len(found), unreferenced=len(found.keys() - named),
                  deleted=len(gone), ms=int((time.monotonic() - started) * 1000))
    await candidates.save(frozenset(survivors))
    return Swept(len(newest), len(newest.keys() - named), deleted)


async def run_once(store: ObjectStore, referenced: Referenced, candidates: Candidates, config: FilesConfig,
                   clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Swept | None:
    """One pass; None when nothing could be judged (no site listed, or the references or candidates could not be
    read or kept: a failure is logged with its frames and nothing is deleted). Logs `files.sweep_started`, one
    `files.sweep_store` per site and `files.swept`."""
    started = time.monotonic()
    logs.info(log, "files.sweep_started")
    try:
        swept = await _pass(store, referenced, candidates, config, clock())
    except Exception:
        logs.error(log, "files.sweep_failed", exc=True, ms=int((time.monotonic() - started) * 1000))
        return None
    if swept is not None:
        logs.info(log, "files.swept", seen=swept.seen, unreferenced=swept.unreferenced, deleted=swept.deleted,
                  ms=int((time.monotonic() - started) * 1000))
    return swept


async def run(store: ObjectStore, referenced: Referenced, candidates: Candidates, config: FilesConfig,
              sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Pass, wait, repeat, until cancelled."""
    while True:
        await run_once(store, referenced, candidates, config)
        await sleep(config.sweep_interval_s)
