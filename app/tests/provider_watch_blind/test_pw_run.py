"""`watch.run`: evaluate, wait `interval_s`, repeat until cancelled; the outage line once per run of failed passes."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import pytest
from ashley import services
from ashley.db.database import Database
from ashley.inference import watch
from ashley.inference.watch import WatchConfig
from provider_watch_blind_support import ALERT, PASS, UNAVAILABLE, Rig, config, fields_of, go, rig

Between = Callable[[int], Awaitable[None]]


async def drive(settings: WatchConfig, passes: int, between: Between) -> list[float]:
    """Run the watch with a sleep that returns at once, calling `between(n)` after the nth sleep started; the
    watch is cancelled when the `passes`th sleep is reached. Returns the delays it was asked to sleep."""
    delays: list[float] = []
    reached = asyncio.Event()

    async def sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= passes:
            reached.set()
            await asyncio.Event().wait()
        await between(len(delays))

    task = asyncio.create_task(watch.run(settings, sleep))
    await asyncio.wait_for(reached.wait(), 15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return delays


async def nothing(n: int) -> None:
    del n


@pytest.fixture(autouse=True)
def info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)


def test_it_evaluates_then_waits_the_interval_and_repeats(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[float]:
        async with rig(db_url):
            return await drive(config(interval_s=7.5), 3, nothing)

    assert go(scenario()) == [7.5, 7.5, 7.5]
    assert len(fields_of(caplog, PASS)) == 3


def test_it_evaluates_before_its_first_wait(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[float]:
        async with rig(db_url):
            return await drive(config(), 1, nothing)

    assert go(scenario()) == [60]
    assert len(fields_of(caplog, PASS)) == 1


def test_an_alert_repeats_each_pass_while_the_share_stays_high_and_stops_when_it_falls(db_url: str,
                                                                                         caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.add("chat", "gemini", "error", 5)

            async def between(n: int) -> None:
                if n == 2:
                    await r.clear()

            await drive(config(), 4, between)

    go(scenario())
    alerts = [len(fields_of(caplog, ALERT))]
    assert alerts == [2]
    assert [f["alerts"] for f in fields_of(caplog, PASS)] == [1, 1, 0, 0]


def test_it_goes_on_past_a_pass_that_could_not_read_the_ledger(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> list[float]:
        async with rig(db_url) as r:
            services.unregister(Database)
            await _seed(r)

            async def between(n: int) -> None:
                if n == 3:
                    services.register(Database, r.db)

            try:
                return await drive(config(), 4, between)
            finally:
                services.register(Database, r.db)

    assert go(scenario()) == [60, 60, 60, 60]
    assert len(fields_of(caplog, PASS)) == 1
    assert len(fields_of(caplog, ALERT)) == 1


async def _seed(r: Rig) -> None:
    await r.add("chat", "gemini", "error", 5)


def test_the_outage_line_is_logged_once_per_run_of_failed_passes(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            services.unregister(Database)

            async def between(n: int) -> None:
                if n == 3:
                    services.register(Database, r.db)
                if n == 4:
                    services.unregister(Database)

            try:
                await drive(config(), 7, between)
            finally:
                services.register(Database, r.db)

    go(scenario())
    assert len(fields_of(caplog, UNAVAILABLE)) == 2
    assert len(fields_of(caplog, PASS)) == 1
