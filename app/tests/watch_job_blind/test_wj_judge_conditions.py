"""The judge's three-way split on `when` and `until`, over conditions the test writes (clause shape of the spec)."""

from typing import Any

from watch_job_blind_support import NEVER, Failed, Quiet, Woke, judged, kinds_of, one, pred, state, watch_of

S = "sess-a"
BASE = one(S, "working", 1)
DONE = one(S, "done", 2)
EVERY = ((pred("changed", "seq"),),)


def check(when: Any, until: Any, read: Any = DONE, baseline: Any = BASE) -> Any:
    return judged(watch_of(baseline=baseline, when=when, until=until), read)


def test_changes_where_when_holds_wake_and_the_baseline_would_move() -> None:
    got = check(EVERY, None)
    assert isinstance(got, Woke) and got.ends is False and got.items == DONE


def test_until_holding_on_a_wake_ends_the_watch_and_the_change_is_still_told() -> None:
    got = check(EVERY, ((pred("equals", "status", value="done"),),))
    assert isinstance(got, Woke) and got.ends is True and kinds_of(got) == [(S, "changed")]


def test_until_not_holding_on_a_wake_leaves_the_watch_running() -> None:
    assert check(EVERY, ((pred("equals", "status", value="idle"),),)).ends is False


def test_changes_where_when_does_not_hold_are_quiet() -> None:
    assert check(NEVER, None) == Quiet(False)


def test_quiet_with_until_holding_ends_the_watch_without_waking() -> None:
    got = check(NEVER, ((pred("equals", "status", value="done"),),))
    assert got == Quiet(True)


def test_no_change_is_quiet_even_when_until_would_hold_on_the_unchanged_item() -> None:
    assert check(EVERY, ((pred("equals", "status", value="working"),),), read=BASE) == Quiet(False)


def test_when_is_judged_only_over_items_that_changed() -> None:
    base = state(one("a", "done", 1), one("b", "working", 1))
    read = state(one("a", "done", 1), one("b", "working", 2))
    when = ((pred("equals", "status", value="done"),),)
    assert check(when, None, read, base) == Quiet(False)


def test_any_one_alternative_is_enough_and_all_predicates_of_it_are_needed() -> None:
    either = ((pred("equals", "status", value="idle"),), (pred("equals", "status", value="done"),))
    both = ((pred("equals", "status", value="done"), pred("number", "seq", min=5)),)
    assert isinstance(check(either, None), Woke)
    assert check(both, None) == Quiet(False)
    assert isinstance(check(((pred("equals", "status", value="done"), pred("number", "seq", min=2)),), None), Woke)


def test_a_new_session_wakes_a_when_that_asks_for_new() -> None:
    got = check(((pred("new"),),), None, read=state(BASE, one("b", "idle", 1)))
    assert isinstance(got, Woke) and kinds_of(got) == [("b", "new")]


def test_a_gone_session_wakes_a_when_that_asks_for_gone_and_the_until_gone_ends_it() -> None:
    got = check(((pred("gone"),),), ((pred("gone"),),), read={})
    assert isinstance(got, Woke) and got.ends is True and kinds_of(got) == [(S, "gone")]
    assert got.changes[0].before == {"status": "working", "seq": 1} and got.changes[0].after is None


def test_a_predicate_on_a_missing_side_is_false_before_negate() -> None:
    read = state(BASE, one("b", "done", 1))   # b is new, so it has no before
    assert check(((pred("equals", "status", of="before", value="done"),),), None, read) == Quiet(False)
    assert isinstance(check(((pred("equals", "status", of="before", value="done", negate=True),),), None, read), Woke)


def test_the_judge_does_not_change_what_it_is_given() -> None:
    base, read = {S: {"status": "working", "seq": 1}}, {S: {"status": "done", "seq": 2}}
    watch = watch_of(baseline=base)
    first = judged(watch, read)
    assert base == BASE and read == DONE and judged(watch, read) == first


def test_a_failed_read_ignores_conditions() -> None:
    from watch_job_blind_support import ReadFailed
    assert check(EVERY, EVERY, read=ReadFailed("bad_result")) == Failed("bad_result")


def test_wj_the_first_read_is_a_baseline_even_when_when_holds_for_every_item_in_it() -> None:
    read = state(one("a", "done", 1), one("b", "done", 2))
    got = judged(watch_of(baseline=None, when=((pred("new"),),)), read)
    assert not isinstance(got, Woke) and got.items == read


def test_wj_when_is_not_judged_over_an_item_that_did_not_change() -> None:
    quiet = state(one("a", "done", 1), one("b", "working", 1))
    read = state(one("a", "done", 1), one("b", "working", 2))
    got = judged(watch_of(baseline=quiet, when=((pred("equals", "status", value="done"),),)), read)
    assert got == Quiet(False)


def test_wj_a_read_with_nothing_changed_is_quiet_whatever_when_would_say_of_its_items() -> None:
    got = judged(watch_of(baseline=DONE, when=((pred("equals", "status", value="done"),),)), DONE)
    assert got == Quiet(False)
