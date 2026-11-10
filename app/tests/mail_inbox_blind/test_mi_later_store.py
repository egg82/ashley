"""The store takes `Later` as a check that records nothing: the watch keeps its baseline, version, series, failures and state,
and is looked at again after `retry_s`, not `interval_s`."""

from ashley.watches.model import Failed, Later
from mail_inbox_blind_store_support import INTERVAL_S, RETRY_S, Store, scenario

KEPT = ("state", "reason", "failures", "version", "series", "baseline", "expires_at", "last_woke_at", "ended_at")


def test_later_is_accepted_and_changes_nothing_a_check_would(db_url: str) -> None:
    async def body(s: Store) -> None:
        a, version = await s.armed_due()
        before = s.row(a)
        assert await s.store.record(a, version, Later()) is True
        after = s.row(a)
        for column in KEPT:
            assert after[column] == before[column], column
        assert s.wakes(a) == 0

    scenario(db_url, body)


def test_later_is_not_a_failure_so_a_run_of_them_never_pauses_and_keeps_the_failures_there_were(db_url: str) -> None:
    async def body(s: Store) -> None:
        a, version = await s.armed_due()
        assert await s.store.record(a, version, Failed("unreachable"))
        for _ in range(10):
            s.make_due(a)
            assert await s.store.record(a, version, Later())
        r = s.row(a)
        assert (r["state"], r["failures"]) == ("armed", 1) and s.wakes(a) == 0

    scenario(db_url, body)


def test_later_defers_the_next_check_by_retry_s_not_interval_s(db_url: str) -> None:
    async def body(s: Store) -> None:
        assert INTERVAL_S < RETRY_S - 100
        a, version = await s.armed_due()
        assert await s.store.record(a, version, Later())
        assert RETRY_S - 30 < s.seconds_until_next(a) <= RETRY_S + 1

    scenario(db_url, body)


def test_a_watch_that_answered_later_is_not_due_until_retry_s_has_passed(db_url: str) -> None:
    async def body(s: Store) -> None:
        a, version = await s.armed_due()
        assert [w.id for w in await s.store.due(50)] == [a]
        assert await s.store.record(a, version, Later())
        assert [w.id for w in await s.store.due(50)] == []
        s.make_due(a)
        assert [w.id for w in await s.store.due(50)] == [a]

    scenario(db_url, body)


def test_a_later_at_a_stale_version_is_lost_like_any_check(db_url: str) -> None:
    async def body(s: Store) -> None:
        a, version = await s.armed_due()
        before = s.row(a)
        assert await s.store.record(a, version + 5, Later()) is False
        assert s.row(a)["next_check_at"] == before["next_check_at"]

    scenario(db_url, body)
