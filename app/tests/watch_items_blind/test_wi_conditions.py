"""Conditions: alternatives of predicates, judged over the changes of one check; arming validation."""

import pytest
from ashley.criteria.items import ItemPredicate
from ashley.criteria.record import Change
from hypothesis import given
from hypothesis import strategies as st
from watch_items_blind_support import (STATUSES, Items, alternative_holds, alternatives, changed, changes, condition_holds,
                                       conditions, diff, eq, holds, is_gone, is_new, item_maps, make_change, one_of,
                                       ref_condition, sess, validate)

MOVED = make_change("s1", sess("working", 3), sess("blocked", 4))
TRACK = ("status", "seq")


def test_an_alternative_needs_every_predicate() -> None:
    assert alternative_holds((eq("status", "blocked"), changed("seq")), MOVED)
    assert not alternative_holds((eq("status", "blocked"), eq("seq", 3)), MOVED)
    assert not alternative_holds((eq("status", "done"), changed("seq")), MOVED)


def test_a_condition_needs_one_alternative() -> None:
    cond = ((eq("status", "done"),), (eq("status", "blocked"), changed("seq")))
    assert condition_holds(cond, [MOVED])
    assert not condition_holds(((eq("status", "done"),), (eq("seq", 9),)), [MOVED])


def test_a_condition_holds_when_some_change_satisfies_it() -> None:
    quiet = make_change("s2", sess("working", 1), sess("working", 2))
    assert condition_holds(((eq("status", "blocked"),),), [quiet, MOVED])
    assert condition_holds(((eq("status", "blocked"),),), [MOVED, quiet])
    assert not condition_holds(((eq("status", "blocked"),),), [quiet])


def test_one_alternative_is_judged_against_one_change_not_a_mix() -> None:
    a = make_change("a", sess("working", 1), sess("blocked", 1))
    b = make_change("b", sess("working", 1), sess("working", 2))
    assert not condition_holds(((eq("status", "blocked"), changed("seq")),), [a, b])


def test_no_changes_satisfies_nothing() -> None:
    assert not condition_holds(((is_new(negate=True),),), [])
    assert not condition_holds(((is_gone(negate=True),),), diff({}, {}))


def test_a_condition_that_is_all_negations_still_needs_a_change() -> None:
    same = {"a": sess("done", 1)}
    assert not condition_holds(((eq("status", "idle", negate=True),),), diff(same, same))


def test_unchanged_items_are_never_judged() -> None:
    before = {"a": sess("done", 1), "b": sess("working", 1)}
    after = {"a": sess("done", 1), "b": sess("working", 1)}
    cond = ((eq("status", "done"),),)
    assert not condition_holds(cond, diff(before, after))
    after["b"] = sess("blocked", 2)
    assert not condition_holds(cond, diff(before, after))
    after["b"] = sess("done", 2)
    assert condition_holds(cond, diff(before, after))


@given(conditions, item_maps(), item_maps())
def test_a_condition_judges_as_the_spec_reads(cond: tuple[tuple[ItemPredicate, ...], ...], a: Items, b: Items) -> None:
    got = diff(a, b)
    assert condition_holds(cond, got) is ref_condition(cond, got)


@given(alternatives, changes())
def test_an_alternative_holds_only_when_all_its_predicates_hold(alt: tuple[ItemPredicate, ...], c: Change) -> None:
    assert alternative_holds(alt, c) is all(holds(p, c) for p in alt)


@given(alternatives, changes())
def test_an_added_failing_predicate_sinks_the_alternative(alt: tuple[ItemPredicate, ...], c: Change) -> None:
    fails = eq("status", "never-a-status")
    assert not alternative_holds((*alt, fails), c)


@given(conditions, item_maps(), item_maps())
def test_unchanged_items_never_satisfy_a_condition(cond: tuple[tuple[ItemPredicate, ...], ...], a: Items,
                                                   b: Items) -> None:
    same = {"zz": sess(STATUSES[0], 1), "yy": sess(STATUSES[2], 7)}
    assert condition_holds(cond, diff({**a, **same}, {**b, **same})) is condition_holds(cond, diff(a, b))
    assert not condition_holds(cond, diff(same, same))


@given(conditions, item_maps(), item_maps())
def test_more_alternatives_never_make_a_condition_false(cond: tuple[tuple[ItemPredicate, ...], ...], a: Items,
                                                        b: Items) -> None:
    got = diff(a, b)
    if condition_holds(cond[:1], got):
        assert condition_holds(cond, got)


# arming validation

def test_a_condition_over_tracked_fields_within_limits_is_accepted() -> None:
    validate(((one_of("status", ["done"]), changed("seq")), (is_gone(),)), TRACK, 4, 4)


def test_a_field_outside_track_is_refused() -> None:
    with pytest.raises(ValueError):
        validate(((eq("label", "x"),),), TRACK, 4, 4)
    with pytest.raises(ValueError):
        validate(((changed("label"),),), TRACK, 4, 4)
    with pytest.raises(ValueError):
        validate(((is_new(), eq("status", "done"), one_of("title", ["a"])),), TRACK, 4, 4)


def test_new_and_gone_need_no_field() -> None:
    validate(((is_new(),), (is_gone(negate=True),)), (), 4, 4)


def test_the_alternative_limit_is_inclusive() -> None:
    alt = (is_gone(),)
    validate((alt,) * 3, TRACK, 3, 4)
    with pytest.raises(ValueError):
        validate((alt,) * 4, TRACK, 3, 4)


def test_the_predicate_limit_is_inclusive_and_counts_each_alternative() -> None:
    validate(((is_new(), is_gone(), changed("seq")),), TRACK, 4, 3)
    with pytest.raises(ValueError):
        validate(((is_new(), is_gone(), changed("seq"), changed("status")),), TRACK, 4, 3)
    with pytest.raises(ValueError):
        validate(((is_new(),), (is_new(), is_gone(), changed("seq"), changed("status"))), TRACK, 4, 3)


@given(st.lists(st.sampled_from(["status", "seq", "label", "x"]), min_size=1, max_size=3))
def test_validation_refuses_exactly_the_fields_outside_track(fields: list[str]) -> None:
    cond = (tuple(changed(f) for f in fields),)
    if all(f in TRACK for f in fields):
        validate(cond, TRACK, 4, 4)
    else:
        with pytest.raises(ValueError):
            validate(cond, TRACK, 4, 4)
