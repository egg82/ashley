"""The watch runs as a singleton under the lease: the wiring hands its name and body to `Lease.run`."""

import asyncio
import logging
from collections.abc import Generator

import pytest
from ashley import services, wiring_singletons
from ashley.inference import watch
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings
from provider_watch_blind_support import ALERT, go, rig, fields_of


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


async def started(settings: Settings) -> None:
    await asyncio.gather(*wiring_singletons.singletons(settings))


def test_with_etcd_the_watch_is_one_of_the_singletons_under_the_lease(lease: RecordingLease) -> None:
    go(started(Settings(database_url="postgresql://x", build_version="t", etcd_url="http://etcd.test:2379")))
    assert watch.NAME == "inference-watch"
    assert "inference-watch" in lease.bodies


def test_without_etcd_the_watch_still_runs_under_the_lease(lease: RecordingLease) -> None:
    go(started(Settings(database_url="postgresql://x", build_version="t")))
    assert "inference-watch" in lease.bodies


def test_the_singletons_body_watches_the_ledger(lease: RecordingLease, db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 5)
            await started(Settings(database_url="postgresql://x", build_version="t", etcd_url="http://etcd.test:2379"))
            task = asyncio.create_task(lease.bodies["inference-watch"]())
            for _ in range(200):
                if fields_of(caplog, ALERT):
                    break
                await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    go(scenario())
    [alert] = fields_of(caplog, ALERT)[:1]
    assert (alert["provider"], alert["calls"], alert["failed"]) == ("gemini", 5, 5)
