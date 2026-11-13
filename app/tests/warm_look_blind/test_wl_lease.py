"""`Lease.run_on_site` as the warm pod's keeper needs it: at most one holder per site, every site has one at the same
time, whichever site is active; the Null lease never runs the body; a holder that stops hands the site over; logs carry
the name with the site and never the standby events."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import Any

import pytest
from ashley.referee.active_site import ActiveSite
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.lease import Body, NullLease
from contract.lease_support import Arena, delete, holder_of, lease_id_of, put, revoke, run, unique_name, wait_until
from etcd import etcd_url

LEADER = "/ashley-test/warm-look-leader"


@asynccontextmanager
async def on_site(lease: EtcdLease, name: str, body: Body) -> AsyncGenerator[asyncio.Task[None]]:
    task = asyncio.create_task(lease.run_on_site(name, body))
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def holder(tag: str, member: str, ttl: int = 2) -> EtcdLease:
    return EtcdLease(etcd_url(), ActiveSite(member, LEADER), ttl=ttl, holder=tag)


def test_two_pods_of_one_site_never_both_run_it() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1")), on_site(holder("a2", "a"), name, arena.body("a2")):
            await wait_until(lambda: arena.starts)
            await asyncio.sleep(0.6)
            assert arena.max_running == 1 and len(arena.starts) == 1

    run(scenario())


def test_each_site_has_a_holder_at_once_and_only_one() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for tag in ("a1", "a2", "b1", "b2", "b3"):
                await stack.enter_async_context(on_site(holder(tag, tag[0]), name, arena.body(tag)))
            await wait_until(lambda: len(arena.starts) >= 2)
            await asyncio.sleep(0.6)
            assert arena.running == 2 and len(arena.starts) == 2
            assert sorted(t[0] for t in arena.starts) == ["a", "b"]

    run(scenario())


@pytest.mark.parametrize("leader", ["a", "b", "someone-else", None])
def test_it_runs_whichever_site_is_active_or_none(leader: str | None) -> None:
    name, arena = unique_name(), Arena()
    if leader is None:
        delete(LEADER)
    else:
        put(LEADER, leader)

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1")):
            await wait_until(lambda: arena.starts)

    run(scenario())


def test_the_standby_site_keeps_its_holder_when_the_other_site_is_active() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("b1", "b"), name, arena.body("b1")):
            await wait_until(lambda: arena.starts == ["b1"])
            await asyncio.sleep(0.8)
            assert arena.running == 1 and arena.cancels == []

    run(scenario())


def test_it_stays_held_when_the_active_site_changes() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1")):
            await wait_until(lambda: arena.starts)
            put(LEADER, "b")
            await asyncio.sleep(0.6)
            put(LEADER, "a")
            await asyncio.sleep(0.2)
            assert arena.running == 1 and arena.cancels == [] and arena.starts == ["a1"]

    run(scenario())


def test_the_sites_own_lease_does_not_block_the_active_site_s_lease_of_the_same_name() -> None:
    name, own, active = unique_name(), Arena(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, own.body("own")):
            await wait_until(lambda: own.starts)
            lease = holder("a2", "a")
            task = asyncio.create_task(lease.run(name, active.body("active")))
            try:
                await wait_until(lambda: active.starts)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            assert own.cancels == []

    run(scenario())


def test_a_holder_that_stops_hands_the_site_to_another_pod() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        first = asyncio.create_task(holder("a1", "a").run_on_site(name, arena.body("a1")))
        await wait_until(lambda: arena.starts == ["a1"])
        async with on_site(holder("a2", "a"), name, arena.body("a2")):
            await asyncio.sleep(0.5)
            assert arena.starts == ["a1"]
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await wait_until(lambda: arena.starts == ["a1", "a2"])
            assert arena.max_running == 1

    run(scenario())


def test_a_lost_lease_stops_the_body_and_it_campaigns_again() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1")):
            await wait_until(lambda: arena.starts == ["a1"])
            lease_id = lease_id_of(name + "@a")
            assert lease_id is not None
            revoke(lease_id)
            await wait_until(lambda: arena.cancels, timeout=8)
            await wait_until(lambda: arena.starts == ["a1", "a1"], timeout=12)
            assert arena.max_running == 1

    run(scenario())


def test_a_body_that_ends_frees_the_site_for_another_pod_at_once() -> None:
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1", first="return")):
            await wait_until(lambda: arena.starts)
            async with on_site(holder("a2", "a"), name, arena.body("a2")):
                await wait_until(lambda: len(arena.starts) >= 2, timeout=8)
                assert arena.max_running == 1

    run(scenario())


def test_it_is_held_under_the_name_with_the_site(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    name, arena = unique_name(), Arena()
    put(LEADER, "a")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1")):
            await wait_until(lambda: arena.starts)

    run(scenario())
    taken = [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == "lease.taken"]
    assert any(t.get("name") == f"{name}@a" for t in taken)
    assert holder_of(name + "@a") is None


def test_waiting_on_another_pod_of_the_site_logs_held_elsewhere_and_never_standby(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    name, arena = unique_name(), Arena()
    put(LEADER, "other")

    async def scenario() -> None:
        async with on_site(holder("a1", "a"), name, arena.body("a1")), on_site(holder("a2", "a"), name, arena.body("a2")):
            await wait_until(lambda: arena.starts)
            await asyncio.sleep(0.6)

    run(scenario())
    events = {r.getMessage() for r in caplog.records}
    assert "lease.held_elsewhere" in events
    assert "lease.standby" not in events
    assert not any(getattr(r, "fields", {}).get("reason") == "not_active_site" for r in caplog.records)


def test_the_null_lease_never_runs_the_body() -> None:
    ran: list[int] = []

    async def body() -> None:
        ran.append(1)

    async def scenario() -> None:
        task: asyncio.Task[Any] = asyncio.create_task(NullLease().run_on_site(unique_name(), body))
        await asyncio.sleep(0.3)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    run(scenario())
    assert ran == []
