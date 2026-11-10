"""Postgres lease contract: mutual exclusion on session advisory locks, release, loss, logging and the wiring.
The controls prove the checks can fail: a lease that never locks must trip the exclusion check."""

import asyncio
import time
from collections.abc import Generator
from contextlib import AsyncExitStack

import pytest
from ashley import logs, services
from ashley.referee.lease import Lease
from ashley.settings import Settings
from ashley.wiring import wire
from ashley.wiring_singletons import singletons
from lease_pg_support import (
    UnlockedLease,
    hold,
    holders,
    max_concurrent_bodies,
    postgres_lease_class,
    release,
    subject,
    terminate,
)
from lease_support import Arena, campaign, events, run, unique_name, wait_until
from pg import throwaway_database


@pytest.fixture(scope="module")
def ci() -> Generator[str]:
    with throwaway_database() as conninfo:
        yield conninfo


def test_control_a_lease_that_never_locks_fails_the_exclusion_check() -> None:
    assert max_concurrent_bodies(lambda tag: UnlockedLease(), unique_name()) == 3


def test_control_the_observer_sees_a_lock_taken_from_outside(ci: str) -> None:
    name = unique_name()
    assert holders(ci, name) == []
    conn = hold(ci, name)
    assert len(holders(ci, name)) == 1
    release(conn, name)
    conn.close()
    assert holders(ci, name) == []


def test_exactly_one_of_three_holders_runs_the_body(ci: str) -> None:
    name, arena = unique_name(), Arena()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            tasks: dict[str, asyncio.Task[None]] = {}
            for i in range(3):
                tasks[f"h{i}"] = await stack.enter_async_context(
                    campaign(subject(ci, holder=f"h{i}"), name, arena.body(f"h{i}"))
                )
            await wait_until(lambda: arena.starts)
            for _ in range(20):
                await asyncio.sleep(0.05)
                assert arena.running == 1
                assert len(holders(ci, name)) == 1
            standbys = [t for tag, t in tasks.items() if tag != arena.starts[0]]
            for t in standbys:
                t.cancel()
            await asyncio.wait(standbys)
        assert arena.starts == arena.starts[:1]
        assert arena.max_running == 1
        assert holders(ci, name) == []

    run(scenario())


def test_distinct_names_do_not_exclude_each_other(ci: str) -> None:
    arena, names = Arena(), [unique_name(), unique_name()]

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for i, name in enumerate(names):
                await stack.enter_async_context(campaign(subject(ci), name, arena.body(f"h{i}")))
            await wait_until(lambda: len(arena.starts) == 2)
            assert all(len(holders(ci, n)) == 1 for n in names)

    run(scenario())


def test_cancelling_run_cancels_the_body_and_frees_the_lock_at_once(ci: str) -> None:
    name, arena = unique_name(), Arena()

    async def scenario() -> None:
        async with campaign(subject(ci, interval=30), name, arena.body("a")) as task:
            await wait_until(lambda: arena.starts)
            assert len(holders(ci, name)) == 1
            task.cancel()
            await asyncio.wait([task])
        assert [tag for tag, _ in arena.cancels] == ["a"]
        assert holders(ci, name) == []

    run(scenario())


@pytest.mark.parametrize("how", ["return", "raise"])
def test_a_body_that_ends_frees_the_lock_and_run_campaigns_again(
    how: str, ci: str, capsys: pytest.CaptureFixture[str]
) -> None:
    logs.setup()
    name, arena = unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            a = await stack.enter_async_context(campaign(subject(ci, holder="a"), name, arena.body("a", how)))
            await wait_until(lambda: arena.starts)
            await stack.enter_async_context(campaign(subject(ci, holder="b"), name, arena.body("b")))
            await wait_until(lambda: len(arena.starts) >= 2, timeout=6)
            assert not a.done(), "a body's failure must not end run"
            assert arena.max_running == 1

    run(scenario())
    out = capsys.readouterr().out
    assert events(out, "lease.released", name)
    assert len(events(out, "lease.taken", name)) >= 2
    assert events(out, "lease.standby") == []
    if how == "raise":
        assert "zqSECRETMESSAGE" not in out


def test_a_server_ended_session_cancels_the_body_logs_lost_and_run_takes_it_again(
    ci: str, capsys: pytest.CaptureFixture[str]
) -> None:
    logs.setup()
    name, arena = unique_name(), Arena()
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(subject(ci), name, arena.body("a")) as task:
            await wait_until(lambda: arena.starts)
            (pid,) = holders(ci, name)
            terminate(ci, pid)
            killed = time.monotonic()
            await wait_until(lambda: arena.cancels, timeout=3)
            assert arena.cancels[0][1] - killed < 1.5
            await wait_until(lambda: len(arena.starts) == 2)
            assert not task.done()
            again = holders(ci, name)
            assert len(again) == 1 and again[0] != pid
            assert arena.max_running == 1

    run(scenario())
    out = capsys.readouterr().out
    assert events(out, "lease.lost", name)
    assert len(events(out, "lease.taken", name)) == 2


def test_a_contender_logs_held_elsewhere_once_per_wait_not_every_poll(
    ci: str, capsys: pytest.CaptureFixture[str]
) -> None:
    logs.setup()
    name, arena = unique_name(), Arena()
    outside = hold(ci, name)
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(subject(ci, interval=0.1), name, arena.body("a")):
            await asyncio.sleep(1.0)
            assert arena.starts == []
            release(outside, name)
            await wait_until(lambda: arena.starts)

    try:
        run(scenario())
    finally:
        outside.close()
    out = capsys.readouterr().out
    assert len(events(out, "lease.held_elsewhere", name)) == 1
    assert len(events(out, "lease.taken", name)) == 1
    assert events(out, "lease.standby") == []


def test_run_on_site_excludes_run_for_the_same_name(ci: str) -> None:
    name, arena = unique_name(), Arena()

    async def scenario() -> None:
        a, b = subject(ci, holder="a"), subject(ci, holder="b")
        tasks = [asyncio.create_task(a.run(name, arena.body("a"))), asyncio.create_task(b.run_on_site(name, arena.body("b")))]
        try:
            await wait_until(lambda: arena.starts)
            for _ in range(10):
                await asyncio.sleep(0.05)
                assert arena.running == 1
            assert len(holders(ci, name)) == 1
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.wait(tasks)
        assert holders(ci, name) == []

    run(scenario())


def test_the_shared_exclusion_measure_reads_one_for_the_subject(ci: str) -> None:
    assert max_concurrent_bodies(lambda tag: subject(ci, holder=tag), unique_name()) == 1


def test_wired_without_etcd_the_locator_answers_a_postgres_lease_that_works(ci: str) -> None:
    name, arena = unique_name(), Arena()
    settings = Settings(database_url=ci, build_version="t", etcd_url="")
    wire(settings)
    lease = services.get(Lease)
    assert isinstance(lease, postgres_lease_class())

    async def scenario() -> None:
        async with campaign(lease, name, arena.body("w")):
            await wait_until(lambda: arena.starts)
            assert len(holders(ci, name)) == 1
        assert holders(ci, name) == []

    run(scenario())
    bodies = singletons(settings)
    assert bodies
    for coroutine in bodies:
        coroutine.close()
