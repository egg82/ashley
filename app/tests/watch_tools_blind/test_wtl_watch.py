"""`watch`: arming reads the target once through the kind, that read is the baseline, a target missing from it is
refused, and the result is the label, the tracked fields now and the expiry in the household's wall clock."""

import asyncio
from datetime import UTC

from watch_tools_blind_fakes import (
    ALANA,
    HOUSE,
    KIND,
    LABEL,
    OTHER,
    SAM,
    TARGET,
    TRACK,
    items,
    without_target,
)
from watch_tools_blind_support import (
    body,
    local,
    minutes_from_now,
    plain,
    refused,
    use,
    world,
)

from ashley.watches.model import ReadFailed


def test_arming_reads_the_target_once_and_stores_that_read_as_the_baseline() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain()))
            assert w.kind.reads == 1
            (arm,) = w.store.armed
            assert arm.baseline[TARGET] == {"status": "working", "seq": 3}
            assert (arm.household_id, arm.person_id, arm.kind, arm.target) == (HOUSE, ALANA, KIND, TARGET)
    asyncio.run(go())


def test_the_watch_is_stored_with_the_kinds_defaults_and_her_own_arming() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(bench_id=4), "watch", plain()))
            (arm,) = w.store.armed
            assert arm.label == LABEL
            assert arm.armed_by == "ashley" and arm.bench_id == 4
            assert tuple(arm.track) == TRACK and arm.when == w.kind.when and arm.interval_s == w.kind.interval_s
            assert arm.tools is None and arm.until == ()
    asyncio.run(go())


def test_the_label_is_the_targets_not_another_sessions() -> None:
    async def go() -> None:
        async with world() as w:
            result = body(await use(w.tools(), "watch", plain()))
            assert LABEL in str(result) and "other" not in str(result)
            assert OTHER not in str(result)
    asyncio.run(go())


def test_the_result_is_the_label_the_tracked_fields_now_and_the_expiry() -> None:
    async def go() -> None:
        async with world() as w:
            result = body(await use(w.tools(), "watch", plain(hours=5)))
            (arm,) = w.store.armed
            assert result["label"] == LABEL
            assert result["tracked"] == {"status": "working", "seq": 3}
            assert result["expires"] == local(arm.expires_at)
    asyncio.run(go())


def test_the_expiry_is_told_in_the_households_wall_clock_not_utc() -> None:
    async def go() -> None:
        async with world() as w:
            result = body(await use(w.tools(), "watch", plain(hours=5)))
            (arm,) = w.store.armed
            assert arm.expires_at.tzinfo is not None
            assert local(arm.expires_at) != arm.expires_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
            assert result["expires"] == local(arm.expires_at)
    asyncio.run(go())


def test_hours_sets_the_expiry_and_the_kinds_hours_is_the_default() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(hours=5)))
            body(await use(w.tools(), "watch", plain()))
            first, second = w.store.armed
            assert minutes_from_now(first.expires_at, 5 * 60)
            assert minutes_from_now(second.expires_at, w.kind.hours * 60)
    asyncio.run(go())


def test_the_longest_a_kind_allows_is_accepted_and_one_more_hour_is_refused() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(hours=w.kind.max_hours)))
            refused(await use(w.tools(), "watch", plain(hours=w.kind.max_hours + 1)), "bad_arguments")
            assert len(w.store.armed) == 1
    asyncio.run(go())


def test_one_hour_is_accepted_and_zero_is_refused() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(hours=1)))
            refused(await use(w.tools(), "watch", plain(hours=0)), "bad_arguments")
            refused(await use(w.tools(), "watch", plain(hours=-3)), "bad_arguments")
            assert len(w.store.armed) == 1 and minutes_from_now(w.store.armed[0].expires_at, 60)
    asyncio.run(go())


def test_hours_is_a_number_and_a_fraction_of_an_hour_is_accepted() -> None:
    async def go() -> None:
        async with world() as w:
            for bad in ("5", True, [5]):
                refused(await use(w.tools(), "watch", plain(hours=bad)), "bad_arguments")
            assert w.store.armed == []
            body(await use(w.tools(), "watch", plain(hours=2.5)))
            assert minutes_from_now(w.store.armed[0].expires_at, 150)
    asyncio.run(go())


def test_a_target_missing_from_the_read_is_refused_not_found_and_nothing_is_stored() -> None:
    async def go() -> None:
        async with world(answer=without_target()) as w:
            refused(await use(w.tools(), "watch", plain()), "not_found")
            assert w.store.armed == [] and w.kind.reads == 1
    asyncio.run(go())


def test_a_read_that_fails_is_never_taken_for_a_missing_target() -> None:
    async def go() -> None:
        async with world(answer=ReadFailed("unreachable")) as w:
            result = await use(w.tools(), "watch", plain())
            refused(result)
            assert not result.content.startswith("not_found")
            assert w.store.armed == []
    asyncio.run(go())


def test_a_kind_that_raises_is_an_error_result_and_arms_nothing() -> None:
    async def go() -> None:
        async with world() as w:
            w.kind.raises = RuntimeError("boom")
            refused(await use(w.tools(), "watch", plain()))
            assert w.store.armed == []
    asyncio.run(go())


def test_arming_needs_no_ok_and_proposes_nothing() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain()))
            assert w.proposals.proposed == [] and len(w.store.armed) == 1
    asyncio.run(go())


def test_arming_works_without_a_turn_to_propose_in() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(turn=None), "watch", plain()))
            assert len(w.store.armed) == 1
    asyncio.run(go())


def test_the_watch_is_for_the_speaker_whoever_the_household_holds() -> None:
    async def go() -> None:
        async with world() as w:
            w.connections.connect(HOUSE, "https://127.0.0.1:7843", "tok2", "herdr", SAM)
            body(await use(w.tools(speaker=SAM), "watch", plain()))
            assert w.store.armed[0].person_id == SAM
    asyncio.run(go())


def test_the_target_and_kind_are_required_text() -> None:
    async def go() -> None:
        async with world() as w:
            for args in ({"kind": KIND}, {"target": TARGET}, {"kind": KIND, "target": ""}, {"kind": KIND, "target": 5},
                         {"kind": KIND, "target": None}, {"kind": 5, "target": TARGET}):
                refused(await use(w.tools(), "watch", args), "bad_arguments")
            assert w.store.armed == [] and w.kind.reads == 0
    asyncio.run(go())


def test_an_argument_the_tool_does_not_define_is_refused() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(when=[[{"kind": "new"}]])), "bad_arguments")
            refused(await use(w.tools(), "watch", plain(interval_s=1)), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


def test_a_store_that_refuses_the_watch_is_an_error_result() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.arm_raises = ValueError("past max_live")
            refused(await use(w.tools(), "watch", plain()), "bad_arguments")
    asyncio.run(go())


def test_a_store_out_of_reach_is_unavailable_not_a_raise() -> None:
    async def go() -> None:
        from ashley.watches.watches import WatchesUnavailable
        async with world() as w:
            w.store.arm_raises = WatchesUnavailable("down")
            refused(await use(w.tools(), "watch", plain()), "unavailable")
    asyncio.run(go())


def test_the_baseline_is_not_refreshed_by_the_listing() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain()))
            reads = w.kind.reads
            await use(w.tools(), "watches")
            assert w.kind.reads == reads
    asyncio.run(go())


def test_a_second_watch_on_the_same_target_reads_again() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain()))
            w.kind.answer = items("done", 4)
            result = body(await use(w.tools(), "watch", plain()))
            assert w.kind.reads == 2 and result["tracked"] == {"status": "done", "seq": 4}
            assert w.store.armed[1].baseline[TARGET] == {"status": "done", "seq": 4}
    asyncio.run(go())
