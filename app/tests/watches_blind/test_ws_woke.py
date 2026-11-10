"""Woke: the baseline, the counters and one wake commit together; one version stores one wake."""

from datetime import datetime

import pytest
from ashley.watches.watches import WatchesUnavailable
from watches_blind_support import (FAIL_AFTER, World, change, changes_of, failed, forbid_watch_wakes, item_id, item_kind,
                                   quiet, row, scenario, settle_wakes, snapshot, version_of, wakes_of, woke)
from contract.conversations_support import gather_settled

ITEMS = {"s1": {"status": "done", "seq": 44}, "s2": {"status": "working", "seq": 1}}
CHANGES = (change("s1", "changed", {"status": "working", "seq": 42}, {"status": "done", "seq": 44}),
           change("s2", "new", None, {"status": "working", "seq": 1}),
           change("s3", "gone", {"status": "idle", "seq": 5}, None))


def test_woke_stores_baseline_counters_and_one_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items={"s1": {"status": "working", "seq": 42}})
        assert await w.store.record(a, version, woke(ITEMS, CHANGES)) is True
        r = row(w.url, a)
        assert (r["baseline"], r["version"], r["series"], r["failures"], r["state"]) == (ITEMS, version + 1, 1, 0, "armed")
        assert r["last_woke_at"] is not None
        (wake,) = wakes_of(w.url, a)
        assert (wake["household_id"], wake["person_id"], wake["kind"], wake["watch_id"]) == (w.hid, w.owner, "watch", a)
        assert wake["event_id"] == f"watch:{a}:{version + 1}"
        assert wake["device_id"] is None and wake["settled_at"] is None and wake["outcome"] is None

    scenario(db_url, body)


def test_the_wake_changes_carry_what_changed(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items={"s1": {"status": "working", "seq": 42}})
        armed_at = row(w.url, a)["armed_at"]
        assert await w.store.record(a, version, woke(ITEMS, CHANGES))
        c = changes_of(wakes_of(w.url, a)[0])
        assert (c["what"], c["series"], c["ended"]) == ("changed", 1, None)
        assert abs((datetime.fromisoformat(c["since"]) - armed_at).total_seconds()) < 2
        by_item = {item_id(i): i for i in c["items"]}
        assert set(by_item) == {"s1", "s2", "s3"} and len(c["items"]) == 3
        assert item_kind(by_item["s1"]) == "changed"
        assert by_item["s1"]["before"] == {"status": "working", "seq": 42}
        assert by_item["s1"]["after"] == {"status": "done", "seq": 44}
        assert (item_kind(by_item["s2"]), by_item["s2"]["before"], by_item["s2"]["after"]) == \
            ("new", None, {"status": "working", "seq": 1})
        assert (item_kind(by_item["s3"]), by_item["s3"]["before"], by_item["s3"]["after"]) == \
            ("gone", {"status": "idle", "seq": 5}, None)

    scenario(db_url, body)


def test_the_second_wake_counts_the_series_and_since_the_last_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, woke(ITEMS, CHANGES))
        first_woke = row(w.url, a)["last_woke_at"]
        settle_wakes(w.url, a)
        assert await w.store.record(a, version + 1, woke({"s1": {"seq": 50}}))
        first, second = wakes_of(w.url, a)
        assert second["event_id"] == f"watch:{a}:{version + 2}" and first["event_id"] != second["event_id"]
        c = changes_of(second)
        assert c["series"] == 2
        assert abs((datetime.fromisoformat(c["since"]) - first_woke).total_seconds()) < 2
        assert row(w.url, a)["series"] == 2

    scenario(db_url, body)


def test_a_second_woke_at_one_version_stores_one_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, woke(ITEMS, CHANGES)) is True
        assert await w.store.record(a, version, woke({"s1": {"seq": 77}})) is False
        assert len(wakes_of(w.url, a)) == 1
        r = row(w.url, a)
        assert (r["baseline"], r["series"], r["version"]) == (ITEMS, 1, version + 1)

    scenario(db_url, body)


def test_racing_wokes_at_one_version_store_one_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        got = await gather_settled(*(w.store.record(a, version, woke({"s1": {"seq": n}})) for n in range(4)))
        assert sorted(map(str, got)) == ["False", "False", "False", "True"], got
        assert len(wakes_of(w.url, a)) == 1 and row(w.url, a)["series"] == 1

    scenario(db_url, body)


def test_woke_that_ends_ends_the_watch_until_and_still_tells_it(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, woke(ITEMS, CHANGES, ends=True))
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["baseline"], r["series"], r["version"]) == \
            ("ended", "until", ITEMS, 1, version + 1)
        assert r["ended_at"] is not None
        (wake,) = wakes_of(w.url, a)
        assert changes_of(wake)["ended"] == "until"

    scenario(db_url, body)


def test_woke_that_does_not_end_leaves_ended_null(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, woke(ITEMS, CHANGES, ends=False))
        assert changes_of(wakes_of(w.url, a)[0])["ended"] is None

    scenario(db_url, body)


def test_woke_after_a_pause_resumes_the_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed())
        assert row(w.url, a)["state"] == "paused"
        assert await w.store.record(a, version, woke(ITEMS, CHANGES))
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["failures"]) == ("armed", None, 0)
        kinds = [changes_of(x)["what"] for x in wakes_of(w.url, a)]
        assert sorted(kinds) == ["changed", "paused"]

    scenario(db_url, body)


def test_a_failed_wake_write_rolls_the_baseline_back(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items={"s1": {"seq": 1}})
        forbid_watch_wakes(w.url)
        before = snapshot(w.url)
        with pytest.raises(WatchesUnavailable):
            await w.store.record(a, version, woke(ITEMS, CHANGES, ends=True))
        assert snapshot(w.url) == before
        r = row(w.url, a)
        assert (r["baseline"], r["version"], r["series"], r["state"]) == ({"s1": {"seq": 1}}, version, 0, "armed")

    scenario(db_url, body)


def test_quiet_and_baseline_write_no_wake_even_when_woke_would(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, quiet())
        assert wakes_of(w.url, a) == [] and version_of(w.url, a) == version

    scenario(db_url, body)
