"""The watches job runs under the lease on real etcd: of two sites campaigning for `watches` one checks, and when it
loses the lease the other takes over from the state in Postgres, so a change wakes her once and is never replayed across
the move. The wiring starts it under that name, and only with etcd; the session sense has no singleton of its own."""

import asyncio
from collections.abc import Generator
from contextlib import AsyncExitStack
from functools import partial

import pytest
from ashley import services, wiring_singletons
from ashley.watches import job as watches_job
from ashley.watches.config import CONFIG
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.lease_support import campaign, holder_of, here, unique_name, wait_until
from contract.conversations_support import run
from etcd import etcd_url
from watch_session_support import told, watching


async def quick(seconds: float) -> None:
    await asyncio.sleep(0.05)


def test_of_two_sites_one_checks_and_the_other_takes_over_from_the_stored_state(
        db_url: str, connection_kinds_wired: None) -> None:
    name = unique_name()

    async def go() -> None:
        async with watching(db_url) as w:
            await w.arm("working", 1001)
            w.bridge.state("working", 1001)
            body = partial(watches_job.run, CONFIG, watches_job.KINDS, quick)
            async with AsyncExitStack() as stack:
                a = EtcdLease(etcd_url(), here(), ttl=2, holder="a")
                b = EtcdLease(etcd_url(), here(), ttl=2, holder="b")
                tasks = {"a": await stack.enter_async_context(campaign(a, name, body)),
                         "b": await stack.enter_async_context(campaign(b, name, body))}
                await wait_until(lambda: holder_of(name) is not None)
                w.bridge.state("blocked", 1002)
                await w.due_now()
                await wait_until(lambda: len(told(db_url)) == 1)
                await w.settle()
                asked = w.bridge.asked
                await asyncio.sleep(0.5)
                assert len(told(db_url)) == 1 and w.bridge.asked - asked <= 12   # one checker, not two
                holder = holder_of(name)
                assert holder in tasks
                tasks[holder].cancel()   # the site holding the lease is lost
                w.bridge.state("done", 1003)
                await w.due_now()
                await wait_until(lambda: len(told(db_url)) == 2)
                await asyncio.sleep(0.3)
            assert [s for _, s in told(db_url)] == ["blocked", "done"] and holder is not None
    run(go())


class RecordingLease(Lease):
    def __init__(self) -> None:
        self.bodies: dict[str, Body] = {}

    async def run(self, name: str, body: Body) -> None:
        self.bodies[name] = body


@pytest.fixture
def lease() -> Generator[RecordingLease]:
    recording = RecordingLease()
    services.register(Lease, recording)
    yield recording


def test_with_etcd_the_wiring_starts_the_watches_job_under_the_lease_named_watches(lease: RecordingLease) -> None:
    async def started(settings: Settings) -> None:
        await asyncio.gather(*wiring_singletons.singletons(settings))

    asyncio.run(started(Settings(database_url="postgresql://x", build_version="t", etcd_url="http://etcd.test:2379")))
    assert watches_job.NAME == "watches" and "watches" in lease.bodies and "herdr_watch" not in lease.bodies
    lease.bodies.clear()
    asyncio.run(started(Settings(database_url="postgresql://x", build_version="t")))
    assert "watches" in lease.bodies and "fail-back" not in lease.bodies
