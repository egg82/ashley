"""`run_on_site`: a lease of this site's own. It is held whichever site leads the database, by one process per site,
and each site holds it at the same time as the other."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from ashley.referee.active_site import ActiveSite
from ashley.referee.etcd_lease import EtcdLease
from etcd import etcd_url
from lease_support import Arena, delete, holder_of, put, run, unique_name, wait_until

LEADER = "/ashley-test/on-site-leader"


@asynccontextmanager
async def on_site(lease: EtcdLease, name: str, body: Any) -> AsyncGenerator[asyncio.Task[None]]:
    task = asyncio.create_task(lease.run_on_site(name, body))
    try:
        yield task
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_it_is_held_while_another_site_leads_and_under_the_sites_own_key() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()
    put(LEADER, "other")

    async def scenario() -> None:
        lease = EtcdLease(url, ActiveSite("a", LEADER), ttl=2, holder="a1")
        async with on_site(lease, name, arena.body("a1")):
            await wait_until(lambda: arena.starts)
            assert holder_of(name + "@a") == "a1" and holder_of(name) is None
        assert holder_of(name + "@a") is None

    run(scenario())


def test_it_is_held_with_no_leader_at_all() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()
    delete(LEADER)

    async def scenario() -> None:
        async with on_site(EtcdLease(url, ActiveSite("a", LEADER), ttl=2, holder="a1"), name, arena.body("a1")):
            await wait_until(lambda: arena.starts)

    run(scenario())


def test_one_process_per_site_runs_and_both_sites_run_at_once() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for tag, member in (("a1", "a"), ("a2", "a"), ("b1", "b"), ("b2", "b")):
                lease = EtcdLease(url, ActiveSite(member, LEADER), ttl=2, holder=tag)
                await stack.enter_async_context(on_site(lease, name, arena.body(tag)))
            await wait_until(lambda: len(arena.starts) >= 2)
            await asyncio.sleep(0.5)
            assert arena.running == 2 and len(arena.starts) == 2
            assert {tag[0] for tag in arena.starts} == {"a", "b"}

    run(scenario())


def test_a_holder_that_stops_hands_the_site_to_another_process() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        first = asyncio.create_task(EtcdLease(url, ActiveSite("a", LEADER), ttl=2, holder="a1").run_on_site(name, arena.body("a1")))
        await wait_until(lambda: arena.starts == ["a1"])
        async with on_site(EtcdLease(url, ActiveSite("a", LEADER), ttl=2, holder="a2"), name, arena.body("a2")):
            await asyncio.sleep(0.5)
            assert arena.starts == ["a1"]
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await wait_until(lambda: arena.starts == ["a1", "a2"], timeout=8)
            assert holder_of(name + "@a") == "a2"

    run(scenario())
