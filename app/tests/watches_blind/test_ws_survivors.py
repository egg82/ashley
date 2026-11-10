"""Directed tests for the planted mutants the blind suite first let through (`MUTANTS.txt`)."""

from datetime import UTC, datetime

import psycopg
import pytest
from contract.conversations_support import scalar
from watches_blind_support import (KEEP_S, World, baseline, changes_of, cond, count, exists, expired_of, failed,
                                   insert_watch, make_arm, pred, pruned_of, row, scenario, version_of, wakes_of, woke)

SLUGS = ("unreachable", "not_connected", "refused", "bad_result", "too_many_items", "unknown_kind")


def test_ws_a_bad_field_in_the_second_of_two_alternatives_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(ValueError):
            await w.store.arm(make_arm(w, when=cond((pred("new"),), (pred("changed", "x"),))))
        assert count(w.url) == 0

    scenario(db_url, body)


def test_ws_an_empty_alternative_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(ValueError):
            await w.store.arm(make_arm(w, when=cond(())))
        assert count(w.url) == 0

    scenario(db_url, body)


def test_ws_a_wake_after_a_baseline_carries_its_series_not_the_version(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        assert await w.store.record(a, version, baseline({"s1": {"seq": 1}}))
        assert await w.store.record(a, version_of(w.url, a), woke({"s1": {"seq": 2}}))
        assert changes_of(wakes_of(w.url, a)[0])["series"] == 1

    scenario(db_url, body)


def test_ws_the_second_wake_is_since_the_first_not_since_arming(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due()
        scalar(w.url, "UPDATE watches SET armed_at = armed_at - interval '2 days' WHERE id = %s RETURNING 1", (a,))
        assert await w.store.record(a, version, woke({"s1": {"seq": 2}}))
        assert await w.store.record(a, version_of(w.url, a), woke({"s1": {"seq": 3}}))
        since = datetime.fromisoformat(changes_of(wakes_of(w.url, a)[1])["since"])
        assert abs((datetime.now(UTC) - since).total_seconds()) < 3600

    scenario(db_url, body)


def test_ws_a_failure_below_the_threshold_checks_again_after_the_watchs_own_interval(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due(interval_s=77)
        assert await w.store.record(a, version, failed())
        ahead = (row(w.url, a)["next_check_at"] - datetime.now(UTC)).total_seconds()
        assert 60 < ahead <= 77

    scenario(db_url, body)


def test_ws_a_live_watch_long_past_its_expiry_is_ended_not_pruned_in_the_same_call(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        scalar(w.url, "UPDATE watches SET armed_at = armed_at - make_interval(secs => %s), "
                      "expires_at = clock_timestamp() - make_interval(secs => %s) WHERE id = %s RETURNING 1",
               (KEEP_S + 200, KEEP_S + 100, a))
        counts = await w.store.expire(KEEP_S)
        assert (expired_of(counts), pruned_of(counts)) == (1, 0)
        assert exists(w.url, a) and row(w.url, a)["reason"] == "expired"

    scenario(db_url, body)


def test_ws_an_ended_watch_takes_no_failure_slug(db_url: str) -> None:
    async def body(w: World) -> None:
        for slug in SLUGS:
            with pytest.raises(psycopg.errors.CheckViolation):
                insert_watch(w.url, household_id=w.hid, person_id=w.owner, state="ended", reason=slug, ended=True)

    scenario(db_url, body)


def test_ws_a_state_outside_the_three_is_refused_even_with_a_reason(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_watch(w.url, household_id=w.hid, person_id=w.owner, state="sleeping", reason="until")

    scenario(db_url, body)


def test_ws_clauses_are_json_arrays_and_the_baseline_an_object(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm()
        for column, bad in (("when_clauses", "{}"), ("until_clauses", "{}"), ("baseline", "[]")):
            with pytest.raises(psycopg.errors.CheckViolation):
                scalar(w.url, f"UPDATE watches SET {column} = %s::jsonb WHERE id = %s RETURNING 1", (bad, a))

    scenario(db_url, body)


def test_ws_the_hot_paths_are_indexed_as_designed(db_url: str) -> None:
    async def body(w: World) -> None:
        defs = " ".join(str(scalar(w.url, "SELECT indexdef FROM pg_indexes WHERE indexname = %s", (n,)))
                        for n in ("watches_next_check", "wakes_watch"))
        assert "(next_check_at)" in defs and "(watch_id)" in defs and defs.count("WHERE") == 2

    scenario(db_url, body)


def test_ws_ended_at_is_set_exactly_when_the_watch_has_ended(db_url: str) -> None:
    async def body(w: World) -> None:
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_watch(w.url, household_id=w.hid, person_id=w.owner, state="ended", reason="until")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_watch(w.url, household_id=w.hid, person_id=w.owner, ended=True)

    scenario(db_url, body)
