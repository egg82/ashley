"""The singleton: its lease name, its loop, and its wiring."""

import asyncio

import pytest
from ashley import logs, services, wiring_singletons
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings
from contract.conversations_support import events
from watch_job_blind_support import CONF, WatchesUnavailable, harness, job, watch_of, run

LOG = "watches.unavailable"


class RecordingLease(Lease):
    def __init__(self) -> None:
        self.bodies: dict[str, Body] = {}

    async def run(self, name: str, body: Body) -> None:
        self.bodies[name] = body


def test_the_lease_is_named_watches() -> None:
    assert job.NAME == "watches"


def test_run_ticks_then_sleeps_tick_s_until_cancelled() -> None:
    h = harness([watch_of(1)], {1: {}})
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError

    async def go() -> None:
        with pytest.raises(asyncio.CancelledError):
            await job.run(CONF, sleep=sleep)
        assert waits == [CONF.tick_s] * 3 and len(h.store.named("due")) == 3 and len(h.store.named("expire")) == 3
    run(go())


def test_run_keeps_going_past_an_unavailable_store_and_logs_the_run_of_failures_once(
        capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    h = harness([], {})
    h.store.broken = WatchesUnavailable("down")
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            h.store.broken = None
        if len(waits) == 5:
            h.store.broken = WatchesUnavailable("down")
        if len(waits) == 7:
            raise asyncio.CancelledError

    async def go() -> None:
        with pytest.raises(asyncio.CancelledError):
            await job.run(CONF, sleep=sleep)
    run(go())
    seen = capsys.readouterr()
    assert len(events(seen.out + seen.err, LOG)) == 2   # tick 1-3 failed (one line), 4-5 fine, 6-7 failed (one line)


def started_under_lease(etcd_url: str) -> dict[str, Body]:
    lease = RecordingLease()
    services.register(Lease, lease)
    settings = Settings(database_url="postgresql://x", build_version="t", etcd_url=etcd_url)
    asyncio.run(asyncio.wait_for(_start(settings), 5))
    return lease.bodies


async def _start(settings: Settings) -> None:
    await asyncio.gather(*wiring_singletons.singletons(settings))


def test_with_etcd_the_wiring_starts_it_under_watches() -> None:
    assert "watches" in started_under_lease("http://etcd.test:2379")


def test_without_etcd_the_wiring_still_starts_it_but_not_failback() -> None:
    bodies = started_under_lease("")
    assert "watches" in bodies and "fail-back" not in bodies


def test_the_wiring_no_longer_starts_herdr_watch() -> None:
    assert "herdr_watch" not in started_under_lease("http://etcd.test:2379")
