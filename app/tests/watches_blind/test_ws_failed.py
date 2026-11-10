"""Failed: failures count up, the watch pauses at fail_after and stores a `paused` wake in the same transaction."""

import pytest
from ashley.watches.watches import WatchesUnavailable
from watches_blind_support import (FAIL_AFTER, World, changes_of, failed, forbid_watch_wakes, quiet, row, scenario,
                                   settle_wakes, snapshot, wakes_of)


def test_failed_counts_up_and_keeps_the_reason_below_the_threshold(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items={"s1": {"seq": 1}})
        for n in range(1, FAIL_AFTER):
            assert await w.store.record(a, version, failed("unreachable")) is True
            r = row(w.url, a)
            assert (r["failures"], r["reason"], r["state"]) == (n, None, "armed")
        assert wakes_of(w.url, a) == []

    scenario(db_url, body)


def test_failed_leaves_baseline_version_and_series_alone(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items={"s1": {"seq": 1}})
        for _ in range(FAIL_AFTER + 2):
            assert await w.store.record(a, version, failed())
        r = row(w.url, a)
        assert (r["baseline"], r["version"], r["series"]) == ({"s1": {"seq": 1}}, version, 0)

    scenario(db_url, body)


def test_failed_at_fail_after_pauses_with_the_last_reason_and_one_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for reason in ("unreachable", "unreachable", "not_connected"):
            assert await w.store.record(a, version, failed(reason))
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["failures"]) == ("paused", "not_connected", FAIL_AFTER)
        (wake,) = wakes_of(w.url, a)
        assert (wake["kind"], wake["watch_id"], wake["person_id"], wake["household_id"]) == ("watch", a, w.owner, w.hid)
        assert wake["settled_at"] is None and wake["device_id"] is None
        c = changes_of(wake)
        assert c["what"] == "paused" and c["reason"] == "not_connected"

    scenario(db_url, body)


def test_the_reason_is_the_latest_one(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER - 1):
            assert await w.store.record(a, version, failed("refused"))
        assert await w.store.record(a, version, failed("bad_result"))
        assert row(w.url, a)["reason"] == "bad_result"

    scenario(db_url, body)


def test_further_failures_while_paused_count_but_store_no_second_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed("unreachable"))
        settle_wakes(w.url, a)
        assert await w.store.record(a, version, failed("too_many_items"))
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["failures"]) == ("paused", "too_many_items", FAIL_AFTER + 1)
        assert len(wakes_of(w.url, a)) == 1

    scenario(db_url, body)


def test_pausing_then_resuming_then_pausing_again_tells_each_pause(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed())
        settle_wakes(w.url, a)
        assert await w.store.record(a, version, quiet())
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed())
        assert len(wakes_of(w.url, a)) == 2

    scenario(db_url, body)


def test_a_failed_pause_wake_write_rolls_the_failure_back(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER - 1):
            assert await w.store.record(a, version, failed())
        forbid_watch_wakes(w.url)
        before = snapshot(w.url)
        with pytest.raises(WatchesUnavailable):
            await w.store.record(a, version, failed())
        assert snapshot(w.url) == before
        assert (row(w.url, a)["state"], row(w.url, a)["failures"]) == ("armed", FAIL_AFTER - 1)

    scenario(db_url, body)


def test_failed_does_not_pause_on_a_stale_version(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER - 1):
            assert await w.store.record(a, version, failed())
        assert await w.store.record(a, version + 5, failed()) is False
        assert (row(w.url, a)["state"], row(w.url, a)["failures"]) == ("armed", FAIL_AFTER - 1)

    scenario(db_url, body)
