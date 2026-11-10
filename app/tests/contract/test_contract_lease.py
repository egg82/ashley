"""Lease contract: mutual exclusion, handover, release, the Null Object and the wiring."""

import asyncio
from contextlib import AsyncExitStack

import pytest
from ashley import logs, services
from ashley.referee.active_site import PATRONI_LEADER_KEY
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.lease import Lease, NullLease
from ashley.referee.postgres_lease import PostgresLease
from ashley.settings import Settings
from ashley.wiring import wire
from etcd import etcd_url
from lease_support import Arena, campaign, events, here, holder_of, put, run, unique_name, wait_until


def test_exactly_one_of_three_holders_runs_the_body() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            tasks: dict[str, asyncio.Task[None]] = {}
            for i in range(3):
                lease = EtcdLease(url, here(), ttl=2, holder=f"h{i}")
                tasks[f"h{i}"] = await stack.enter_async_context(campaign(lease, name, arena.body(f"h{i}")))
            await wait_until(lambda: arena.starts)
            for _ in range(40):
                await asyncio.sleep(0.05)
                assert arena.running == 1
            winner = arena.starts[0]
            assert holder_of(name) == winner
            standbys = [t for tag, t in tasks.items() if tag != winner]
            for t in standbys:
                t.cancel()
            await asyncio.wait(standbys)
        assert len(arena.starts) == 1
        assert arena.max_running == 1
        assert holder_of(name) is None

    run(scenario())


def test_distinct_names_do_not_exclude_each_other() -> None:
    url, arena = etcd_url(), Arena()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for i in range(2):
                lease = EtcdLease(url, here(), ttl=2, holder=f"h{i}")
                await stack.enter_async_context(campaign(lease, unique_name(), arena.body(f"h{i}")))
            await wait_until(lambda: len(arena.starts) == 2)

    run(scenario())


def test_cancelling_run_cancels_the_body_and_frees_the_key_at_once() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=30, holder="a"), name, arena.body("a")) as task:
            await wait_until(lambda: arena.starts)
            assert holder_of(name) == "a"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert [tag for tag, _ in arena.cancels] == ["a"]
        assert arena.running == 0
        assert holder_of(name) is None

    run(scenario())


def test_the_standby_takes_over_promptly_when_the_holder_is_cancelled() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            a = await stack.enter_async_context(campaign(EtcdLease(url, here(), ttl=10, holder="a"), name, arena.body("a")))
            await wait_until(lambda: arena.starts)
            await stack.enter_async_context(campaign(EtcdLease(url, here(), ttl=10, holder="b"), name, arena.body("b")))
            await asyncio.sleep(0.5)
            assert arena.starts == ["a"]
            a.cancel()
            await asyncio.wait({a})
            assert holder_of(name) != "a"
            await wait_until(lambda: arena.starts == ["a", "b"], timeout=6)
            assert arena.max_running == 1
            assert holder_of(name) == "b"

    run(scenario())


def test_a_waiting_run_that_is_cancelled_never_takes_the_key() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, here(), ttl=30, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            async with campaign(EtcdLease(url, here(), ttl=30, holder="b"), name, arena.body("b")) as waiting:
                await asyncio.sleep(0.3)
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting
            assert holder_of(name) == "a"
        assert holder_of(name) is None

    run(scenario())


@pytest.mark.parametrize("how", ["return", "raise"])
def test_a_body_that_ends_frees_the_lease_at_once_and_run_campaigns_again(
    how: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """ttl=10: were the key left to expire, neither holder could start a second body within the 6 s allowed."""
    logs.setup()
    url, name, arena = etcd_url(), unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            a = await stack.enter_async_context(campaign(EtcdLease(url, here(), ttl=10, holder="a"), name, arena.body("a", how)))
            await wait_until(lambda: arena.starts)
            await stack.enter_async_context(campaign(EtcdLease(url, here(), ttl=10, holder="b"), name, arena.body("b")))
            await wait_until(lambda: len(arena.starts) >= 2, timeout=6)
            assert not a.done(), "a body's failure must not end run"
            assert arena.max_running == 1

    run(scenario())
    out = capsys.readouterr().out
    released = events(out, "lease.released", name)
    assert released and all(ln.get("reason") for ln in released)
    assert len(events(out, "lease.taken", name)) >= 2
    if how == "raise":
        assert "zqSECRETMESSAGE" not in out
        assert any("ValueError" in ln and "tb=" in ln for ln in out.splitlines() if "lease." in ln)


def test_null_lease_never_runs_a_body_and_can_be_cancelled() -> None:
    lease = Lease.null()
    arena = Arena()
    assert isinstance(lease, NullLease)

    async def scenario() -> None:
        async with campaign(lease, unique_name(), arena.body("n")) as task:
            await asyncio.sleep(0.3)
            assert not task.done()
        assert arena.starts == []

    run(scenario())


def test_unwired_the_locator_answers_the_null_lease() -> None:
    assert isinstance(services.get(Lease), NullLease)


def test_wired_with_an_etcd_url_the_locator_answers_an_etcd_lease_that_works() -> None:
    url, name, arena = etcd_url(), unique_name(), Arena()
    put(PATRONI_LEADER_KEY, "w")
    wire(Settings(database_url="postgresql://127.0.0.1:1/none", build_version="t", etcd_url=url, site="w"))
    lease = services.get(Lease)
    assert isinstance(lease, EtcdLease)

    async def scenario() -> None:
        async with campaign(lease, name, arena.body("w")):
            await wait_until(lambda: arena.starts)
            assert holder_of(name) is not None
        assert holder_of(name) is None

    run(scenario())


def test_wired_without_an_etcd_url_the_locator_answers_the_postgres_lease() -> None:
    wire(Settings(database_url="postgresql://127.0.0.1:1/none", build_version="t", etcd_url=""))
    assert isinstance(services.get(Lease), PostgresLease)
