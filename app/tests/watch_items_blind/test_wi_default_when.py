"""The `claude_session` default `when`, from the spec, as worked examples over diff: a stop or a block wakes her;
`working` does not; `done` becoming `idle` wakes nothing."""

from collections.abc import Mapping

import pytest
from ashley.criteria.items import ItemPredicate
from watch_items_blind_support import DEFAULT_WHEN, Items, Scalar, condition_holds, diff, sess, validate


def wakes(before: Items, after: Items) -> bool:
    return condition_holds(DEFAULT_WHEN, diff(before, after))


def test_the_default_is_a_valid_condition_over_status_and_seq() -> None:
    validate(DEFAULT_WHEN, ("status", "seq"), 4, 4)
    assert len(DEFAULT_WHEN) == 2 and all(isinstance(p, ItemPredicate) for alt in DEFAULT_WHEN for p in alt)


@pytest.mark.parametrize("old,new", [
    (sess("working", 41), sess("blocked", 42)),
    (sess("working", 41), sess("done", 42)),
    (sess("idle", 3), sess("blocked", 4)),
    (sess("done", 42), sess("done", 44)),
    (sess("blocked", 5), sess("done", 6)),
    (sess("done", 42), sess("done", 1)),
    (sess("working", 41), sess("idle", 42)),
    (sess("blocked", 5), sess("idle", 6)),
])
def test_a_stop_a_block_or_a_new_finish_wakes(old: Mapping[str, Scalar], new: Mapping[str, Scalar]) -> None:
    assert wakes({"s": old}, {"s": new})


@pytest.mark.parametrize("old,new", [
    (sess("done", 42), sess("idle", 43)),
    (sess("done", 42), sess("idle", 42)),
    (sess("working", 41), sess("working", 42)),
    (sess("blocked", 5), sess("working", 6)),
    (sess("done", 42), sess("working", 43)),
    (sess("idle", 3), sess("working", 4)),
    (sess("blocked", 5), sess("blocked", 5)),
    (sess("done", 42), sess("done", 42)),
    (sess("idle", 3), sess("idle", 3)),
    (sess("working", 1), sess("working", 1)),
])
def test_working_idle_after_done_and_no_news_do_not_wake(old: Mapping[str, Scalar], new: Mapping[str, Scalar]) -> None:
    assert not wakes({"s": old}, {"s": new})


def test_a_blocked_status_with_no_new_seq_does_not_wake() -> None:
    assert not wakes({"s": sess("working", 5)}, {"s": sess("blocked", 5)})


def test_a_session_first_seen_replays_nothing() -> None:
    assert not wakes({}, {"s": sess("done", 9)})
    assert not wakes({}, {"s": sess("blocked", 9)})


def test_a_session_that_closed_wakes_nothing() -> None:
    assert not wakes({"s": sess("done", 9)}, {})
    assert not wakes({"s": sess("blocked", 9)}, {})


def test_a_second_finish_since_the_last_wake_wakes_though_the_status_matches() -> None:
    assert wakes({"s": sess("done", 42)}, {"s": sess("done", 44)})


def test_a_run_between_two_wakes_reads_as_one_finish() -> None:
    assert wakes({"s": sess("done", 42)}, {"s": sess("done", 44)})
    assert not wakes({"s": sess("done", 44)}, {"s": sess("idle", 45)})


def test_one_session_stopping_wakes_among_quiet_ones() -> None:
    before = {"a": sess("working", 1), "b": sess("working", 1), "c": sess("done", 7)}
    after = {"a": sess("working", 2), "b": sess("done", 2), "c": sess("done", 7)}
    assert wakes(before, after)
    after["b"] = sess("working", 3)
    assert not wakes(before, after)
