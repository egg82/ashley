"""Lease contract under faults: loss by revoke, loss by partition, and what is logged about waiting and failing. On the
fake etcd and the virtual clock (`lease_support.FakeStand`); the revoke runs against the real etcd too."""

import asyncio
from contextlib import AsyncExitStack

import pytest
from ashley import logs
from etcd_fake import Link
from lease_support import Arena, FakeStand, RealStand, campaign, events, unique_name, wait_until


@pytest.mark.parametrize("stand", [RealStand, FakeStand], ids=["real", "fake"])
def test_a_revoked_lease_cancels_the_body_logs_the_loss_and_campaigns_again(
    stand: type[RealStand | FakeStand], capsys: pytest.CaptureFixture[str],
) -> None:
    logs.setup()
    etcd, name, arena = stand(), unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(etcd.lease(etcd.here(), ttl=2, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            first = etcd.lease_id_of(name)
            assert first is not None
            etcd.revoke(first)
            await wait_until(lambda: arena.cancels, timeout=6)
            assert arena.running == 0
            await wait_until(lambda: len(arena.starts) == 2, timeout=10)
            assert etcd.holder_of(name) == "a"
            assert etcd.lease_id_of(name) != first

    etcd.run(scenario())
    out = capsys.readouterr().out
    assert len(events(out, "lease.lost", name)) == 1
    assert len(events(out, "lease.taken", name)) == 2


def test_a_partitioned_holder_stops_its_body_before_etcd_frees_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    """The key must still be held, in etcd's own view, at the instant the body sees its cancellation; the standby on
    a healthy link starts only afterwards, and the two bodies never overlap."""
    logs.setup()
    etcd, name, arena, link = FakeStand(), unique_name(), Arena(), Link()
    seen: list[str | None] = []
    arena.on_cancel = lambda: seen.append(etcd.holder_of(name))
    capsys.readouterr()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(campaign(etcd.lease(etcd.here(), 3, "a", link), name, arena.body("a")))
            await wait_until(lambda: arena.starts)
            await stack.enter_async_context(campaign(etcd.lease(etcd.here(), 3, "b"), name, arena.body("b")))
            await asyncio.sleep(0.5)
            link.down = True
            await wait_until(lambda: arena.cancels, timeout=6)
            assert seen == ["a"], "the key was already free in etcd when the body was cancelled"
            assert arena.starts == ["a"]
            await wait_until(lambda: arena.starts == ["a", "b"], timeout=10)
            assert arena.max_running == 1

    etcd.run(scenario())
    assert len(events(capsys.readouterr().out, "lease.lost", name)) == 1


def test_a_partitioned_holder_leaves_its_body_time_to_clean_up_before_etcd_frees_the_key() -> None:
    """The stop margin is for the body: one that takes a moment to wind down still finishes while the key is held."""
    etcd, name, link = FakeStand(), unique_name(), Link()
    seen: list[str | None] = []

    async def body() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.sleep(0.3)
            seen.append(etcd.holder_of(name))

    async def scenario() -> None:
        async with campaign(etcd.lease(etcd.here(), 3, "a", link), name, body):
            await wait_until(lambda: etcd.holder_of(name) == "a")
            link.down = True
            await wait_until(lambda: seen, timeout=6)
            assert seen == ["a"], "the key was free in etcd before the body finished stopping"

    etcd.run(scenario())


def test_waiting_on_another_holder_is_logged_once_not_once_per_retry(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    etcd, name, arena = FakeStand(), unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(etcd.lease(etcd.here(), 30, "a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            async with campaign(etcd.lease(etcd.here(), 30, "b"), name, arena.body("b")):
                await asyncio.sleep(4)
                assert arena.starts == ["a"]

    etcd.run(scenario())
    out = capsys.readouterr().out
    assert len(events(out, "lease.held_elsewhere", name)) == 1
    assert len(events(out, "lease.taken", name)) == 1


def test_etcd_unreachable_is_logged_once_per_streak_and_carries_no_address(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The line carries only the client's error, which over the real gateway names no address
    (`test_contract_etcd_client.py`)."""
    logs.setup()
    etcd, name, arena, link = FakeStand(), unique_name(), Arena(), Link(down=True)
    capsys.readouterr()

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        async with campaign(etcd.lease(etcd.here(), 2, "a", link), name, arena.body("a")):
            await asyncio.sleep(2.5)
            assert arena.starts == []
            link.down = False
            await wait_until(lambda: arena.starts)
            start = loop.time()
            link.down = True
            await wait_until(lambda: arena.cancels, timeout=6)
            assert loop.time() - start < 6
            await asyncio.sleep(1.5)

    etcd.run(scenario())
    unreachable = events(capsys.readouterr().out, "lease.etcd_unreachable")
    assert len(unreachable) == 2
    assert [line["error"] for line in unreachable] == ["ConnectError", "ConnectError"]


def test_a_run_cancelled_just_after_etcd_granted_it_the_key_leaves_no_key_behind() -> None:
    """The standby's transaction has been applied by etcd, its answer is still on the way, and the run is cancelled:
    the key must not be left for its TTL to clear."""
    etcd, name, arena, slow = FakeStand(), unique_name(), Arena(), Link()

    async def scenario() -> None:
        async with campaign(etcd.lease(etcd.here(), 30, "a"), name, arena.body("a")) as a:
            await wait_until(lambda: arena.starts)
            async with campaign(etcd.lease(etcd.here(), 30, "b", slow), name, arena.body("b")) as b:
                await asyncio.sleep(0.5)
                slow.txn_delay = 0.8
                a.cancel()
                await wait_until(lambda: etcd.holder_of(name) == "b", timeout=15)
                b.cancel()
                await asyncio.wait({b})
                assert etcd.holder_of(name) is None
        assert arena.starts == ["a"]

    etcd.run(scenario())
