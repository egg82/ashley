"""The sweep runs as a singleton under the lease: pass, wait `sweep_interval_s`, repeat, until cancelled; and
at most one holder of the lease `files-sweep` sweeps at any moment."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from functools import partial

from ashley.files import sweep
from ashley.files.mirror import MirroredStore
from ashley import services
from ashley.files.store import ObjectStore
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings
from ashley.wiring_singletons import singletons
from contract.lease_support import campaign, here, unique_name, wait_until
from files_sweep_blind_support import CONFIG, OLD, Clock, Site, go, key, rig


def test_the_lease_is_named_files_sweep() -> None:
    assert sweep.NAME == "files-sweep"


def test_run_passes_waits_the_configured_interval_and_goes_on_until_cancelled(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.clock.now = datetime.now(UTC)
            for s in r.sites:
                s.keep(key(1), age=OLD)
            waits: list[float] = []

            async def sleep(seconds: float) -> None:
                waits.append(seconds)
                if len(waits) == 3:
                    raise asyncio.CancelledError
                await asyncio.sleep(0)

            task = asyncio.create_task(sweep.run(r.mirror, r.named, r.candidates, r.config, sleep))
            with suppress(asyncio.CancelledError):
                await task
            assert waits == [CONFIG.sweep_interval_s] * 3
            assert r.holders(key(1)) == [False, False]

    go(scenario())


def test_cancelling_run_ends_it(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            task = asyncio.create_task(sweep.run(r.mirror, r.named, r.candidates, r.config))
            await asyncio.sleep(0.3)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            assert task.done()

    go(scenario())


def test_of_two_pods_under_the_lease_only_one_sweeps(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.clock.now = datetime.now(UTC)
            other = [Site(r.clock, "x"), Site(r.clock, "y")]
            for s in [*r.sites, *other]:
                s.keep(key(1), age=OLD)
            pods = [MirroredStore(list(r.sites)), MirroredStore(list(other))]
            name = unique_name()
            url = _etcd()
            async with campaign(EtcdLease(url, here(), ttl=3, holder="a"), name,
                                partial(sweep.run, pods[0], r.named, r.candidates, r.config)):
                await wait_until(lambda: any(s.of("listing") for s in r.sites))
                async with campaign(EtcdLease(url, here(), ttl=3, holder="b"), name,
                                    partial(sweep.run, pods[1], r.named, r.candidates, r.config)):
                    await asyncio.sleep(1.5)
                    assert not any(s.of("listing") for s in other)
                    assert all(s.of("listing") for s in r.sites)

    go(scenario())


def _etcd() -> str:
    from etcd import etcd_url
    return etcd_url()


class NamedLeases(Lease):
    """A lease that only records the names it is asked to run bodies under."""

    def __init__(self) -> None:
        self.names: list[str] = []

    async def run(self, name: str, body: Body) -> None:
        self.names.append(name)


def _wired(store: ObjectStore) -> list[str]:
    leases = NamedLeases()
    services.register(Lease, leases)
    services.register(ObjectStore, store)
    try:
        settings = Settings(database_url="x", build_version="t", etcd_url="http://127.0.0.1:1", site="willow")
        for coroutine in singletons(settings):
            asyncio.run(coroutine)
        return leases.names
    finally:
        services.unregister(Lease)
        services.unregister(ObjectStore)


def test_the_app_starts_the_sweep_under_the_lease_when_the_store_spans_sites() -> None:
    clock = Clock()
    names = _wired(MirroredStore([Site(clock), Site(clock, "b")]))
    assert names.count(sweep.NAME) == 1


def test_the_app_does_not_start_the_sweep_without_a_mirrored_store() -> None:
    assert sweep.NAME not in _wired(Site(Clock()))
