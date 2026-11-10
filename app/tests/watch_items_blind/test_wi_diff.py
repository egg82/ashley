"""diff over Items: identity -> tracked scalars; only new, changed and gone items are reported."""

from collections.abc import Mapping

import pytest
from ashley.criteria.record import Change
from hypothesis import given
from watch_items_blind_support import Items, Scalar, diff, item_maps, sess

SWAP = {"new": "gone", "gone": "new", "changed": "changed"}


def by_id(got: tuple[Change, ...]) -> dict[str, Change]:
    out = {c.id: c for c in got}
    assert len(out) == len(got), "one change per item"
    return out


def test_nothing_changed_is_empty() -> None:
    assert diff({}, {}) == ()
    same = {"a": sess("done", 1), "b": sess("working", 2)}
    assert diff(same, dict(same)) == ()


def test_an_item_only_in_the_later_read_is_new() -> None:
    got = by_id(diff({"a": sess("done", 1)}, {"a": sess("done", 1), "b": sess("working", 2)}))
    assert set(got) == {"b"}
    assert (got["b"].kind, got["b"].before, got["b"].after) == ("new", None, sess("working", 2))


def test_an_item_only_in_the_earlier_read_is_gone() -> None:
    got = by_id(diff({"a": sess("done", 1), "b": sess("working", 2)}, {"a": sess("done", 1)}))
    assert set(got) == {"b"}
    assert (got["b"].kind, got["b"].before, got["b"].after) == ("gone", sess("working", 2), None)


def test_an_item_whose_tracked_field_differs_is_changed_with_both_sides() -> None:
    got = by_id(diff({"a": sess("working", 1)}, {"a": sess("blocked", 1)}))
    assert (got["a"].kind, got["a"].before, got["a"].after) == ("changed", sess("working", 1), sess("blocked", 1))


@pytest.mark.parametrize("old,new", [(sess("done", 1), sess("done", 2)), (sess("done", 1), sess("idle", 1))])
def test_any_one_field_differing_is_a_change(old: Mapping[str, Scalar], new: Mapping[str, Scalar]) -> None:
    assert by_id(diff({"a": old}, {"a": new}))["a"].kind == "changed"


def test_new_changed_and_gone_are_reported_together_and_the_rest_left_out() -> None:
    before = {"keep": sess("done", 1), "move": sess("working", 1), "go": sess("idle", 1)}
    after = {"keep": sess("done", 1), "move": sess("done", 2), "add": sess("working", 0)}
    got = by_id(diff(before, after))
    assert {i: c.kind for i, c in got.items()} == {"move": "changed", "go": "gone", "add": "new"}


def test_none_null_and_false_are_values_like_any_other() -> None:
    assert diff({"a": {"v": None}}, {"a": {"v": None}}) == ()
    assert by_id(diff({"a": {"v": None}}, {"a": {"v": False}}))["a"].kind == "changed"
    assert by_id(diff({"a": {"v": 0}}, {"a": {"v": None}}))["a"].kind == "changed"


def test_text_is_cut_to_max_value_chars_before_it_is_kept() -> None:
    got = by_id(diff({}, {"a": {"label": "abcdefghij"}}, max_value_chars=4))
    assert got["a"].after == {"label": "abcd"}


def test_text_cut_to_the_same_prefix_is_not_a_change() -> None:
    assert diff({"a": {"label": "abcdXXXX"}}, {"a": {"label": "abcdYYYY"}}, max_value_chars=4) == ()
    got = by_id(diff({"a": {"label": "abcdXXXX"}}, {"a": {"label": "abxdYYYY"}}, max_value_chars=4))
    assert got["a"].kind == "changed"


def test_text_within_the_limit_is_kept_whole_and_numbers_are_never_cut() -> None:
    got = by_id(diff({}, {"a": {"label": "abcd", "n": 123456789}}, max_value_chars=4))
    assert got["a"].after == {"label": "abcd", "n": 123456789}


@given(item_maps())
def test_diff_of_a_read_with_itself_is_empty(a: Items) -> None:
    assert diff(a, a) == ()
    assert diff(a, {k: dict(v) for k, v in a.items()}) == ()


@given(item_maps(), item_maps())
def test_diff_the_other_way_swaps_new_and_gone_and_before_and_after(a: Items, b: Items) -> None:
    fwd, back = by_id(diff(a, b)), by_id(diff(b, a))
    assert set(fwd) == set(back)
    for i, c in fwd.items():
        r = back[i]
        assert (r.kind, r.before, r.after) == (SWAP[c.kind], c.after, c.before)


@given(item_maps(), item_maps())
def test_diff_reports_exactly_the_items_that_differ(a: Items, b: Items) -> None:
    got = by_id(diff(a, b))
    assert set(got) == {i for i in a.keys() | b.keys() if a.get(i) != b.get(i)}
    for i, c in got.items():
        assert c.before == a.get(i) and c.after == b.get(i)
