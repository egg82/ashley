"""Lease contract under faults: loss by revoke, loss by partition, and what is logged about waiting and failing."""

import asyncio
import time
from contextlib import AsyncExitStack

import pytest
from ashley import logs
from ashley.referee.etcd_lease import EtcdLease
from etcd import etcd_url
from lease_support import (
    Arena, SlowTxn, Switch, campaign, events, here, holder_of, lease_id_of, revoke, run, unique_name, wait_until,
)


def test_a_revoked_lease_cancels_the_body_logs_the_loss_and_campaigns_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs.setup()
    url, name, arena = etcd_url(), unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=3, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            first = lease_id_of(name)
            assert first is not None
            revoke(first)
            await wait_until(lambda: arena.cancels, timeout=6)
            assert arena.running == 0
            await wait_until(lambda: len(arena.starts) == 2, timeout=10)
            assert holder_of(name) == "a"
            assert lease_id_of(name) != first

    run(scenario())
    out = capsys.readouterr().out
    assert len(events(out, "lease.lost", name)) == 1
    assert len(events(out, "lease.taken", name)) == 2


def test_a_partitioned_holder_stops_its_body_before_etcd_frees_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    """The key must still be held, in etcd's own view, at the instant the body sees its cancellation; the standby on
    a healthy link starts only afterwards, and the two bodies never overlap."""
    logs.setup()
    url, name, arena = etcd_url(), unique_name(), Arena()
    switch = Switch()
    seen: list[str | None] = []
    arena.on_cancel = lambda: seen.append(holder_of(name))
    capsys.readouterr()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            lease_a = EtcdLease(url, here(), ttl=3, holder="a", transport=switch)
            await stack.enter_async_context(campaign(lease_a, name, arena.body("a")))
            await wait_until(lambda: arena.starts)
            await stack.enter_async_context(campaign(EtcdLease(url, here(), ttl=3, holder="b"), name, arena.body("b")))
            await asyncio.sleep(0.5)
            switch.down = True
            await wait_until(lambda: arena.cancels, timeout=6)
            assert seen == ["a"], "the key was already free in etcd when the body was cancelled"
            assert arena.starts == ["a"]
            await wait_until(lambda: arena.starts == ["a", "b"], timeout=10)
            assert arena.max_running == 1

    run(scenario())
    assert len(events(capsys.readouterr().out, "lease.lost", name)) == 1


def test_a_partitioned_holder_leaves_its_body_time_to_clean_up_before_etcd_frees_the_key() -> None:
    """The stop margin is for the body: one that takes a moment to wind down still finishes while the key is held."""
    url, name = etcd_url(), unique_name()
    switch = Switch()
    seen: list[str | None] = []

    async def body() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.sleep(0.3)
            seen.append(holder_of(name))

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=3, holder="a", transport=switch), name, body):
            await wait_until(lambda: holder_of(name) == "a")
            switch.down = True
            await wait_until(lambda: seen, timeout=6)
            assert seen == ["a"], "the key was free in etcd before the body finished stopping"

    run(scenario())

def test_waiting_on_another_holder_is_logged_once_not_once_per_retry(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    url, name, arena = etcd_url(), unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=30, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            async with campaign(EtcdLease(url, here(), ttl=30, holder="b"), name, arena.body("b")):
                await asyncio.sleep(4)
                assert arena.starts == ["a"]

    run(scenario())
    out = capsys.readouterr().out
    assert len(events(out, "lease.held_elsewhere", name)) == 1
    assert len(events(out, "lease.taken", name)) == 1


def test_etcd_unreachable_is_logged_once_per_streak_and_carries_no_address(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs.setup()
    url, name, arena = etcd_url(), unique_name(), Arena()
    switch = Switch()
    switch.down = True
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=2, holder="a", transport=switch), name, arena.body("a")):
            await asyncio.sleep(2.5)
            assert arena.starts == []
            switch.down = False
            await wait_until(lambda: arena.starts)
            start = time.monotonic()
            switch.down = True
            await wait_until(lambda: arena.cancels, timeout=6)
            assert time.monotonic() - start < 6
            await asyncio.sleep(1.5)

    run(scenario())
    out = capsys.readouterr().out
    assert len(events(out, "lease.etcd_unreachable")) == 2
    assert url not in out and url.split("//", 1)[1] not in out


def test_a_run_cancelled_just_after_etcd_granted_it_the_key_leaves_no_key_behind() -> None:
    """The standby's transaction has been applied by etcd, its answer is still on the way, and the run is cancelled:
    the key must not be left for its TTL to clear."""
    url, name, arena = etcd_url(), unique_name(), Arena()
    slow = SlowTxn()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=30, holder="a"), name, arena.body("a")) as a:
            await wait_until(lambda: arena.starts)
            async with campaign(EtcdLease(url, here(), ttl=30, holder="b", transport=slow), name, arena.body("b")) as b:
                await asyncio.sleep(0.5)
                slow.slow = True
                a.cancel()
                await wait_until(lambda: holder_of(name) == "b", timeout=15)
                b.cancel()
                await asyncio.wait({b})
                assert holder_of(name) is None
        assert arena.starts == ["a"]

    run(scenario())
