"""The pure judge under the claude_session defaults: the session sense's cases (`test_herdr_watch.py`) ported."""

from typing import Any

import pytest
from watch_job_blind_support import (DEFAULT_UNTIL, DEFAULT_WHEN, Baseline, Failed, Quiet, Woke, ReadFailed, judged,
                                     kinds_of, one, state, watch_of)

S = "sess-a"


def verdict(before: tuple[str, int] | None, after: tuple[str, int] | None, **over: Any) -> Any:
    baseline = None if before is None else one(S, *before)
    read = {} if after is None else one(S, *after)
    return judged(watch_of(baseline=baseline, **over), read)


def test_the_first_successful_read_is_a_silent_baseline_even_when_it_would_wake() -> None:
    read = one(S, "done", 9)
    assert judged(watch_of(baseline=None), read) == Baseline(read)


def test_an_empty_first_read_is_still_a_baseline() -> None:
    assert judged(watch_of(baseline=None), {}) == Baseline({})


@pytest.mark.parametrize("recorded,seen,wakes", [
    (("idle", 5), ("done", 6), True), (("working", 6), ("blocked", 7), True), (("done", 6), ("done", 6), False),
    (("blocked", 7), ("blocked", 7), False), (("idle", 5), ("working", 6), False), (("idle", 5), ("idle", 6), True),
    (("idle", 5), ("unknown", 6), False), (("working", 6), ("done", 8), True), (("working", 6), ("idle", 7), True),
    (("done", 6), ("idle", 7), False), (("done", 900), ("idle", 3), False), (("idle", 7), ("idle", 7), False),
    (("done", 9), ("done", 10), True), (("working", 900), ("done", 3), True),
    (("done", 42), ("done", 44), True),
    (("done", 900), ("done", 3), True)])   # a herdr restart reset seq, the status is unchanged: now wakes
def test_the_default_when_wakes_on_a_finish_or_a_block_and_not_on_a_look(
        recorded: tuple[str, int], seen: tuple[str, int], wakes: bool) -> None:
    got = verdict(recorded, seen)
    assert isinstance(got, Woke) if wakes else isinstance(got, Quiet)


def test_a_wake_carries_the_whole_read_and_the_change_with_its_sides() -> None:
    got = verdict(("done", 42), ("done", 44))
    assert got.ends is False and got.items == one(S, "done", 44)
    [change] = got.changes
    assert (change.id, change.kind) == (S, "changed")
    assert change.before == {"status": "done", "seq": 42} and change.after == {"status": "done", "seq": 44}


def test_a_quiet_check_says_it_does_not_end_the_watch() -> None:
    assert verdict(("done", 6), ("idle", 7)) == Quiet(False)
    assert verdict(("done", 6), ("done", 6)) == Quiet(False)


def test_a_session_closed_with_the_handoff_until_ends_silently() -> None:
    assert verdict(("done", 6), None) == Quiet(True)
    assert verdict(("working", 6), None) == Quiet(True)


def test_a_session_still_there_does_not_end_the_handoff_watch() -> None:
    assert verdict(("working", 6), ("blocked", 7)).ends is False
    assert verdict(("working", 6), ("working", 7)).ends is False


def test_the_shipped_defaults_are_the_spec_conditions() -> None:
    from watch_job_blind_support import CONFIG
    assert CONFIG.kinds["claude_session"].when == DEFAULT_WHEN
    assert CONFIG.kinds["claude_session"].handoff_until == DEFAULT_UNTIL


@pytest.mark.parametrize("reason", ["unreachable", "not_connected", "refused", "bad_result", "too_many_items",
                                    "unknown_kind"])
def test_a_failed_read_is_a_failed_check_with_its_reason(reason: Any) -> None:
    assert judged(watch_of(baseline=one(S, "done", 6)), ReadFailed(reason)) == Failed(reason)
    assert judged(watch_of(baseline=None), ReadFailed(reason)) == Failed(reason)


def test_a_failure_is_never_the_session_being_gone() -> None:
    got = judged(watch_of(baseline=one(S, "done", 6)), ReadFailed("unreachable"))
    assert isinstance(got, Failed) and not isinstance(got, Quiet)


def test_a_failure_does_not_end_a_watch_whose_until_is_gone() -> None:
    assert judged(watch_of(baseline=one(S, "done", 6), until=DEFAULT_UNTIL), ReadFailed("refused")) == Failed("refused")


def test_a_paused_watch_that_reads_again_is_diffed_against_its_baseline_from_before_the_pause() -> None:
    paused = watch_of(baseline=one(S, "working", 6), state="paused", reason="unreachable", failures=3)
    got = judged(paused, one(S, "done", 9))
    assert isinstance(got, Woke) and kinds_of(got) == [(S, "changed")]
    assert got.changes[0].before == {"status": "working", "seq": 6}
    assert judged(paused, one(S, "working", 6)) == Quiet(False)


def test_a_paused_watch_that_reads_a_first_time_baselines() -> None:
    assert judged(watch_of(baseline=None, state="paused", failures=3), one(S, "idle", 1)) == Baseline(one(S, "idle", 1))


def test_between_two_wakes_a_run_of_moves_reads_as_one_finish_since_the_last() -> None:
    baseline = one(S, "done", 3)   # the last wake
    for status, seq in (("idle", 4), ("working", 5)):
        assert judged(watch_of(baseline=baseline), one(S, status, seq)) == Quiet(False)   # the baseline stays put
    got = judged(watch_of(baseline=baseline), one(S, "done", 6))
    assert isinstance(got, Woke) and kinds_of(got) == [(S, "changed")]
    before, after = got.changes[0].before, got.changes[0].after
    assert before is not None and after is not None
    assert before["seq"] == 3 and after["seq"] == 6 and got.items == one(S, "done", 6)


def test_the_baseline_moves_only_on_a_wake() -> None:
    """Driven as the store does: a Woke replaces the baseline, nothing else does."""
    baseline: Any = one(S, "working", 1)
    woke = 0
    for status, seq in (("done", 2), ("idle", 3), ("working", 4), ("done", 5), ("done", 5), ("blocked", 6)):
        got = judged(watch_of(baseline=baseline), one(S, status, seq))
        if isinstance(got, Woke):
            woke += 1
            assert got.changes[0].before == baseline[S]
            baseline = got.items
    assert woke == 3 and baseline == one(S, "blocked", 6)


def test_several_sessions_in_one_read_judge_each_and_tell_every_change() -> None:
    base = state(one("a", "working", 1), one("b", "done", 5), one("c", "idle", 2))
    read = state(one("a", "done", 2), one("b", "done", 5), one("d", "blocked", 1))
    got = judged(watch_of(baseline=base, until=None), read)
    assert isinstance(got, Woke)
    assert kinds_of(got) == [("a", "changed"), ("c", "gone"), ("d", "new")]
