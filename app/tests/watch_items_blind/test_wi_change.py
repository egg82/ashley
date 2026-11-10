"""Change: one item's identity, whether it is new, changed or gone, and its tracked fields before and after."""

from watch_items_blind_support import Change, diff, make_change, sess


def test_a_change_from_diff_equals_the_one_built_by_hand() -> None:
    assert diff({"a": sess("working", 1)}, {"a": sess("done", 2)}) == (
        make_change("a", sess("working", 1), sess("done", 2)),)
    assert diff({}, {"a": sess("working", 1)}) == (make_change("a", None, sess("working", 1)),)
    assert diff({"a": sess("working", 1)}, {}) == (make_change("a", sess("working", 1), None),)


def test_changes_with_different_sides_differ() -> None:
    assert make_change("a", sess("done", 1), sess("done", 2)) != make_change("a", sess("done", 1), sess("done", 3))
    assert make_change("a", None, sess("done", 1)) != make_change("a", sess("done", 1), None)


def test_equal_changes_compare_equal() -> None:
    c: Change = make_change("a", None, sess("done", 1))
    assert c == make_change("a", None, sess("done", 1))
