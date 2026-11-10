"""A kind that raises or hangs, a store that is down, and cancellation."""

import asyncio
from dataclasses import replace

import pytest
from watch_job_blind_support import (CONF, Failed, Hang, Quiet, WatchesUnavailable, always, for_person, harness, one, run,
                                     watch_of)


def two_people() -> list[object]:
    return [watch_of(1, person_id=7, target="a", baseline={}), watch_of(2, person_id=7, target="b", baseline={}),
            watch_of(3, person_id=8, target="c", baseline={})]


def test_a_kind_that_raises_fails_every_watch_of_its_group_and_not_the_others() -> None:
    h = harness(two_people(), {3: {}})
    h.kind.script = for_person(7, RuntimeError("boom"))

    async def go() -> None:
        await h.tick()
        checks = h.store.checks()
        assert isinstance(checks[1], Failed) and isinstance(checks[2], Failed) and checks[3] == Quiet(False)
    run(go())


def test_a_read_that_outlasts_read_timeout_fails_its_group_and_the_tick_still_ends() -> None:
    h = harness(two_people(), {3: {}}, replace(CONF, read_timeout_s=0.05))
    h.kind.script = for_person(7, Hang())

    async def go() -> None:
        await asyncio.wait_for(h.tick(), 2.0)
        checks = h.store.checks()
        assert isinstance(checks[1], Failed) and isinstance(checks[2], Failed) and checks[3] == Quiet(False)
    run(go())


def test_cancelling_a_tick_in_a_hung_read_cancels_it_and_records_nothing() -> None:
    h = harness([watch_of(1)], {})
    h.kind.script = always(Hang())

    async def go() -> None:
        task = asyncio.create_task(h.tick())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert h.store.named("record") == []
    run(go())


def test_a_store_that_is_unavailable_fails_the_tick_with_watches_unavailable() -> None:
    h = harness([watch_of(1)], {1: one("a", "idle", 1)})
    h.store.broken = WatchesUnavailable("down")

    async def go() -> None:
        with pytest.raises(WatchesUnavailable):
            await h.tick()
        assert h.kind.groups == [] and h.store.named("record") == []
    run(go())
