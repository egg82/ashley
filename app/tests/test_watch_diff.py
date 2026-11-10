"""`ashley.watches.diff.diff` turns two reads into the new, changed and gone items, and `to_items` keeps tracked fields
to scalars cut to a length."""

import pytest
from ashley.criteria.record import Change
from ashley.watches.diff import Items, diff, to_items

A: Items = {"s1": {"status": "working", "seq": 1}, "s2": {"status": "idle", "seq": 7}}
B: Items = {"s1": {"status": "done", "seq": 2}, "s3": {"status": "working", "seq": 1}}


def test_new_changed_and_gone_in_identity_order() -> None:
    assert diff(A, B) == (
        Change("s1", "changed", A["s1"], B["s1"]), Change("s2", "gone", A["s2"], None),
        Change("s3", "new", None, B["s3"]))


def test_unchanged_items_and_equal_reads_are_empty() -> None:
    assert diff(A, A) == () and diff({}, {}) == ()
    assert diff(A, {**A, "s2": {"seq": 7.0, "status": "idle"}}) == ()


def test_a_boolean_is_not_the_number_it_equals() -> None:
    assert len(diff({"a": {"f": 1}}, {"a": {"f": True}})) == 1


def test_swapping_the_reads_swaps_new_and_gone() -> None:
    kinds = {"new": "gone", "gone": "new", "changed": "changed"}
    assert [(c.id, kinds[c.kind]) for c in diff(A, B)] == [(c.id, c.kind) for c in diff(B, A)]


def test_to_items_cuts_text_and_refuses_non_scalars() -> None:
    assert to_items({"a": {"t": "abcdef", "n": 1, "b": False, "z": None, "f": 1.5}}, 3) == {
        "a": {"t": "abc", "n": 1, "b": False, "z": None, "f": 1.5}}
    for bad in ([1], {"x": 1}, float("inf"), float("nan"), b"x"):
        with pytest.raises(ValueError):
            to_items({"a": {"k": bad}}, 3)
