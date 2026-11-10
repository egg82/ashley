"""The job is a singleton: its lease is named `errands`, the wiring starts it under that name (with etcd or without),
and its body ticks, waits `tick_s` and ticks again until cancelled."""

import asyncio
from collections.abc import Callable, Generator
from contextlib import suppress

import pytest
from ashley import services, wiring_singletons
from ashley.channels import errand as job
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings
from job_blind_support import CONF, LEASE_NAME, Hang, job_of, opened, run, state_of


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


async def until(done: Callable[[], bool], seconds: float = 5.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if done():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("did not happen in time")


async def stopped(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.wait({task}, timeout=5)
    assert task.done(), "the job kept running after it was cancelled"
    with suppress(asyncio.CancelledError):
        await task


def test_the_lease_is_named_errands() -> None:
    assert job.NAME == LEASE_NAME == "errands"


def test_with_etcd_the_job_is_one_of_the_singletons_under_the_lease(lease: RecordingLease) -> None:
    async def started() -> None:
        await asyncio.gather(*wiring_singletons.singletons(
            Settings(database_url="postgresql://x", build_version="t", etcd_url="http://etcd.test:2379")))

    run(started())
    assert LEASE_NAME in lease.bodies


def test_without_etcd_the_job_still_runs_under_the_lease(lease: RecordingLease) -> None:
    async def started() -> None:
        await asyncio.gather(*wiring_singletons.singletons(Settings(database_url="postgresql://x", build_version="t")))

    run(started())
    assert LEASE_NAME in lease.bodies


def test_the_wired_body_runs_a_due_errand(lease: RecordingLease, db_url: str) -> None:
    async def scenario() -> None:
        async with opened(db_url) as w:
            eid = await w.owe()
            await asyncio.gather(*wiring_singletons.singletons(
                Settings(database_url="postgresql://x", build_version="t", etcd_url="http://etcd.test:2379")))
            task = asyncio.create_task(lease.bodies[LEASE_NAME]())
            await until(lambda: state_of(w.url, eid) == "done")
            await stopped(task)

    run(scenario())


def test_run_ticks_again_and_again_until_cancelled(db_url: str) -> None:
    async def scenario() -> None:
        async with opened(db_url) as w:
            task = asyncio.create_task(w.job.run())
            await until(lambda: len(w.errands.named("sweep")) >= 3)
            await stopped(task)
            after = len(w.errands.named("sweep"))
            await asyncio.sleep(0.1)
            assert len(w.errands.named("sweep")) == after

    run(scenario())


def test_run_does_the_work_that_arrives_between_ticks(db_url: str) -> None:
    async def scenario() -> None:
        async with opened(db_url) as w:
            task = asyncio.create_task(w.job.run())
            await asyncio.sleep(0.05)
            first = await w.owe()
            await until(lambda: state_of(w.url, first) == "done")
            second = await w.owe()
            await until(lambda: state_of(w.url, second) == "done")
            await stopped(task)

    run(scenario())


def test_run_waits_tick_s_between_ticks(db_url: str) -> None:
    from dataclasses import replace

    async def scenario() -> None:
        slow = replace(CONF, tick_s=0.5)
        async with opened(db_url, slow) as w:
            task = asyncio.create_task(job_of(slow).run())
            await asyncio.sleep(0.3)
            await stopped(task)
            assert len(w.errands.named("sweep")) == 1

    run(scenario())


def test_cancelling_a_tick_in_flight_stops_the_job(db_url: str) -> None:
    async def scenario() -> None:
        async with opened(db_url) as w:
            await w.owe()
            w.model.play(Hang())
            task = asyncio.create_task(w.job.run())
            await asyncio.wait_for(w.model.hanging.wait(), 5)
            await stopped(task)

    run(scenario())

