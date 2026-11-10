"""arm raises ValueError before writing: fields outside track, conditions over their limits, expiry not in the future,
a new watch past max_live."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from watches_blind_support import (FAIL_AFTER, MAX_ALTS, MAX_LIVE, MAX_PREDS, UNTIL_GONE, World, cond, count, failed,
                                   make_arm, pred, row, scenario, snapshot, version_of)


async def refused(w: World, target: str = "s1", **more: Any) -> None:
    before = snapshot(w.url)
    with pytest.raises(ValueError):
        await w.store.arm(make_arm(w, target, **more))
    assert snapshot(w.url) == before


def test_a_when_field_outside_track_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        await refused(w, when=cond((pred("equals", "colour", value="red"),)))
        assert count(w.url) == 0

    scenario(db_url, body)


def test_an_until_field_outside_track_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        await refused(w, until=cond((pred("changed", "colour"),)))

    scenario(db_url, body)


def test_every_predicate_kind_with_a_field_is_checked_against_track(db_url: str) -> None:
    async def body(w: World) -> None:
        for p in (pred("one_of", "x", values=["a"]), pred("number", "x", min=1), pred("contains", "x", text="a"),
                  pred("changed", "x"), pred("equals", "x", value="a", of="before")):
            await refused(w, when=cond((pred("new"), p)))

    scenario(db_url, body)


def test_a_bad_field_in_a_later_alternative_is_still_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        await refused(w, when=cond((pred("new"),), (pred("changed", "seq"),), (pred("changed", "x"),)))

    scenario(db_url, body)


def test_predicates_without_a_field_need_no_tracked_field(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.arm(when=cond((pred("new"),), (pred("gone"),)), until=UNTIL_GONE)
        assert count(w.url) == 1

    scenario(db_url, body)


def test_too_many_alternatives_is_refused_and_the_limit_is_allowed(db_url: str) -> None:
    async def body(w: World) -> None:
        one = (pred("changed", "seq"),)
        await refused(w, when=cond(*([one] * (MAX_ALTS + 1))))
        await refused(w, until=cond(*([one] * (MAX_ALTS + 1))))
        await w.arm(when=cond(*([one] * MAX_ALTS)))
        assert count(w.url) == 1

    scenario(db_url, body)


def test_too_many_predicates_is_refused_and_the_limit_is_allowed(db_url: str) -> None:
    async def body(w: World) -> None:
        p = pred("changed", "seq")
        await refused(w, when=cond((p,) * (MAX_PREDS + 1)))
        await refused(w, until=cond((p,) * (MAX_PREDS + 1)))
        await w.arm(when=cond((p,) * MAX_PREDS))
        assert count(w.url) == 1

    scenario(db_url, body)


def test_expiry_not_in_the_future_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        await refused(w, expires_at=datetime.now(UTC) - timedelta(minutes=1))
        await refused(w, expires_at=datetime.now(UTC) - timedelta(days=3))

    scenario(db_url, body)


def test_a_refused_rearm_leaves_the_live_watch_as_it_was(db_url: str) -> None:
    async def body(w: World) -> None:
        wid = await w.arm()
        before = row(w.url, wid)
        await refused(w, when=cond((pred("changed", "x"),)), interval_s=99)
        await refused(w, expires_at=datetime.now(UTC) - timedelta(minutes=1), interval_s=99)
        assert row(w.url, wid) == before

    scenario(db_url, body)


def test_a_new_watch_past_max_live_is_refused(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(MAX_LIVE):
            await w.arm(f"t{i}")
        await refused(w, "one-too-many")
        assert count(w.url) == MAX_LIVE

    scenario(db_url, body)


def test_arming_an_existing_target_at_max_live_is_not_a_new_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(MAX_LIVE):
            await w.arm(f"t{i}")
        await w.arm("t0", interval_s=45)
        assert count(w.url) == MAX_LIVE

    scenario(db_url, body)


def test_max_live_counts_per_person(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(MAX_LIVE):
            await w.arm(f"t{i}")
        await w.arm("t0", who=w.mate)
        assert count(w.url) == MAX_LIVE + 1

    scenario(db_url, body)


def test_ended_watches_do_not_count_toward_max_live(db_url: str) -> None:
    async def body(w: World) -> None:
        for i in range(MAX_LIVE):
            await w.arm(f"t{i}")
        assert await w.store.disarm(w.hid, w.owner, "claude_session", "t0")
        await w.arm("fresh")
        assert len([r for r in await w.store.live(w.hid, w.owner)]) == MAX_LIVE

    scenario(db_url, body)


def test_paused_watches_count_toward_max_live(db_url: str) -> None:
    async def body(w: World) -> None:
        first = await w.arm("t0")
        for _ in range(FAIL_AFTER):
            assert await w.store.record(first, version_of(w.url, first), failed())
        assert row(w.url, first)["state"] == "paused"
        for i in range(1, MAX_LIVE):
            await w.arm(f"t{i}")
        await refused(w, "one-too-many")

    scenario(db_url, body)
