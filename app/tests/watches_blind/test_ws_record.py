"""record: Baseline and Quiet, the version condition, resuming, and when the next check falls."""

from watches_blind_support import (FAIL_AFTER, INTERVAL_S, RETRY_S, World, baseline, defer, failed, quiet, row,
                                   scenario, seconds_until, snapshot, version_of, wakes_of, woke)

BASE = {"s1": {"status": "working", "seq": 3}}


def test_baseline_stores_the_items_and_raises_the_version(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, baseline(BASE)) is True
        r = row(w.url, a)
        assert (r["baseline"], r["version"], r["failures"], r["series"], r["state"]) == (BASE, version + 1, 0, 0, "armed")
        assert wakes_of(w.url, a) == []

    scenario(db_url, body)


def test_a_second_baseline_replaces_the_first(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, baseline(BASE))
        newer = {"s1": {"status": "done", "seq": 9}}
        assert await w.store.record(a, version + 1, baseline(newer))
        r = row(w.url, a)
        assert (r["baseline"], r["version"]) == (newer, version + 2)

    scenario(db_url, body)


def test_record_at_a_stale_version_changes_nothing_and_says_false(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, baseline(BASE))
        before = snapshot(w.url)
        for check in (baseline({"x": {"seq": 1}}), quiet(), quiet(ends=True), woke({"x": {"seq": 1}}), failed()):
            assert await w.store.record(a, version, check) is False
        assert snapshot(w.url) == before

    scenario(db_url, body)


def test_record_at_a_version_ahead_of_the_watch_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        before = snapshot(w.url)
        assert await w.store.record(a, version + 1, baseline(BASE)) is False
        assert snapshot(w.url) == before

    scenario(db_url, body)


def test_record_of_an_unknown_watch_is_false(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await w.store.record(424242, 0, baseline(BASE)) is False

    scenario(db_url, body)


def test_record_on_an_ended_watch_is_false_and_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.disarm(w.hid, w.owner, "claude_session", "s1")
        before = snapshot(w.url)
        for check in (baseline(BASE), quiet(), woke(BASE), failed()):
            assert await w.store.record(a, version, check) is False
        assert snapshot(w.url) == before

    scenario(db_url, body)


def test_quiet_keeps_the_baseline_and_version(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items=BASE)
        assert await w.store.record(a, version, quiet()) is True
        r = row(w.url, a)
        assert (r["baseline"], r["version"], r["series"], r["state"], r["ended_at"]) == (BASE, version, 0, "armed", None)
        assert wakes_of(w.url, a) == []

    scenario(db_url, body)


def test_quiet_that_ends_ends_the_watch_until_without_a_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items=BASE)
        assert await w.store.record(a, version, quiet(ends=True)) is True
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["baseline"], r["version"]) == ("ended", "until", BASE, version)
        assert r["ended_at"] is not None and wakes_of(w.url, a) == []

    scenario(db_url, body)


def test_quiet_after_a_failure_resumes_and_resets_failures(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(items=BASE)
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed("refused"))
        paused = row(w.url, a)
        assert (paused["state"], paused["reason"], paused["failures"]) == ("paused", "refused", FAIL_AFTER)
        assert await w.store.record(a, version, quiet())
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["failures"], r["baseline"]) == ("armed", None, 0, BASE)

    scenario(db_url, body)


def test_baseline_after_a_pause_resumes(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed())
        assert await w.store.record(a, version, baseline(BASE))
        r = row(w.url, a)
        assert (r["state"], r["reason"], r["failures"], r["version"]) == ("armed", None, 0, version + 1)

    scenario(db_url, body)


def test_a_success_below_the_threshold_resets_the_count(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        for _ in range(FAIL_AFTER - 1):
            assert await w.store.record(a, version, failed())
        assert row(w.url, a)["failures"] == FAIL_AFTER - 1
        assert await w.store.record(a, version, quiet())
        assert row(w.url, a)["failures"] == 0 and row(w.url, a)["reason"] is None
        for _ in range(FAIL_AFTER - 1):
            assert await w.store.record(a, version, failed())
        assert row(w.url, a)["state"] == "armed"

    scenario(db_url, body)


def test_next_check_is_interval_s_from_now_after_each_success(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm(interval_s=INTERVAL_S)
        for check in (baseline(BASE), quiet(), woke(BASE)):
            defer(w.url, a, 99_999)
            assert await w.store.record(a, version_of(w.url, a), check)
            assert 0 < seconds_until(w.url, a, "next_check_at") <= INTERVAL_S + 1
            assert seconds_until(w.url, a, "next_check_at") > INTERVAL_S - 30

    scenario(db_url, body)


def test_next_check_uses_the_watchs_own_interval(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm(interval_s=900)
        assert await w.store.record(a, 0, quiet())
        assert 800 < seconds_until(w.url, a, "next_check_at") <= 901

    scenario(db_url, body)


def test_next_check_is_retry_s_while_paused(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm(interval_s=INTERVAL_S)
        for _ in range(FAIL_AFTER - 1):
            assert await w.store.record(a, 0, failed())
            assert 0 < seconds_until(w.url, a, "next_check_at") <= INTERVAL_S + 1
        assert await w.store.record(a, 0, failed())
        assert RETRY_S - 30 < seconds_until(w.url, a, "next_check_at") <= RETRY_S + 1
        assert await w.store.record(a, 0, failed())
        assert RETRY_S - 30 < seconds_until(w.url, a, "next_check_at") <= RETRY_S + 1

    scenario(db_url, body)


def test_next_check_returns_to_interval_s_after_resuming(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm(interval_s=INTERVAL_S)
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, 0, failed())
        assert await w.store.record(a, 0, quiet())
        assert 0 < seconds_until(w.url, a, "next_check_at") <= INTERVAL_S + 1

    scenario(db_url, body)


def test_a_stale_record_does_not_move_next_check(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, baseline(BASE))
        before = row(w.url, a)["next_check_at"]
        assert await w.store.record(a, version, quiet()) is False
        assert row(w.url, a)["next_check_at"] == before

    scenario(db_url, body)
