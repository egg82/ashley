"""ItemPredicate: each kind's meaning on a Change, `of` before and after, `negate`, and a missing side."""

import pytest
from ashley.criteria.items import ItemPredicate
from ashley.criteria.record import Change
from hypothesis import given
from watch_items_blind_support import (changed, changes, eq, has, holds, is_gone, is_new, make_change, negated, num,
                                       one_of, predicates, ref_holds, sess)

NEW = make_change("s1", None, sess("working", 3))
GONE = make_change("s1", sess("done", 9), None)
MOVED = make_change("s1", sess("working", 3), sess("blocked", 4))


def test_a_change_names_its_item_its_state_and_both_sides() -> None:
    assert (MOVED.id, MOVED.kind, MOVED.before, MOVED.after) == ("s1", "changed", sess("working", 3),
                                                                      sess("blocked", 4))
    assert (NEW.kind, NEW.before) == ("new", None) and (GONE.kind, GONE.after) == ("gone", None)
    assert isinstance(MOVED, Change)


def test_a_change_is_immutable() -> None:
    with pytest.raises(AttributeError):
        setattr(MOVED, "kind", "gone")


def test_a_predicate_is_a_value() -> None:
    assert eq("status", "done") == eq("status", "done") and eq("status", "done") != eq("status", "idle")
    with pytest.raises(AttributeError):
        setattr(eq("status", "done"), "negate", True)
    assert isinstance(eq("status", "done"), ItemPredicate)


@pytest.mark.parametrize("value,want", [("blocked", True), ("working", False), ("BLOCKED", False)])
def test_equals_reads_the_item_after_the_change_by_default(value: str, want: bool) -> None:
    assert holds(eq("status", value), MOVED) is want


def test_equals_of_before_reads_the_earlier_side() -> None:
    assert holds(eq("status", "working", of="before"), MOVED)
    assert not holds(eq("status", "blocked", of="before"), MOVED)


def test_equals_compares_numbers_and_the_other_scalars() -> None:
    assert holds(eq("seq", 4), MOVED) and not holds(eq("seq", 3), MOVED) and holds(eq("seq", 3, of="before"), MOVED)
    c = make_change("x", None, {"open": True, "due": None})
    assert holds(eq("open", True), c) and not holds(eq("open", False), c)


def test_equals_with_a_null_value_is_refused() -> None:
    with pytest.raises(ValueError):
        eq("due", None)


@pytest.mark.parametrize("values,want", [(["blocked", "done"], True), (["done"], False), (["working", "blocked"], True),
                                         (["Blocked"], False)])
def test_one_of_holds_when_the_field_is_any_listed_value(values: list[str], want: bool) -> None:
    assert holds(one_of("status", values), MOVED) is want


def test_one_of_of_before_reads_the_earlier_side() -> None:
    assert holds(one_of("status", ["working", "idle"], of="before"), MOVED)
    assert not holds(one_of("status", ["blocked"], of="before"), MOVED)


@pytest.mark.parametrize("lo,hi,want", [(4, None, True), (5, None, False), (None, 4, True), (None, 3, False),
                                        (4, 4, True), (3, 5, True), (5, 9, False), (0, 3, False)])
def test_number_bounds_are_inclusive_and_either_may_be_open(lo: int | None, hi: int | None, want: bool) -> None:
    assert holds(num("seq", lo, hi), MOVED) is want


def test_number_of_before_reads_the_earlier_side() -> None:
    assert holds(num("seq", 3, 3, of="before"), MOVED) and not holds(num("seq", 4, None, of="before"), MOVED)


def test_number_on_a_non_number_is_false() -> None:
    assert not holds(num("status", 0, 100), MOVED)
    assert not holds(num("open", 0, 100), make_change("x", None, {"open": True}))


@pytest.mark.parametrize("text,want", [("lock", True), ("BLOCK", True), ("Blocked", True), ("done", False)])
def test_contains_is_a_case_insensitive_substring(text: str, want: bool) -> None:
    assert holds(has("status", text), MOVED) is want


def test_contains_with_empty_text_is_refused() -> None:
    with pytest.raises(ValueError):
        has("status", "")


def test_contains_of_before_reads_the_earlier_side_and_ignores_non_text() -> None:
    assert holds(has("status", "WORK", of="before"), MOVED) and not holds(has("status", "block", of="before"), MOVED)
    assert not holds(has("seq", "4"), MOVED)


def test_new_and_gone_read_the_state_of_the_change() -> None:
    assert holds(is_new(), NEW) and not holds(is_new(), MOVED) and not holds(is_new(), GONE)
    assert holds(is_gone(), GONE) and not holds(is_gone(), MOVED) and not holds(is_gone(), NEW)


def test_changed_is_true_when_that_field_differs() -> None:
    assert holds(changed("status"), MOVED) and holds(changed("seq"), MOVED)
    same_status = make_change("s1", sess("done", 42), sess("done", 44))
    assert holds(changed("seq"), same_status) and not holds(changed("status"), same_status)


def test_changed_is_false_on_a_new_or_gone_item() -> None:
    assert not holds(changed("status"), NEW) and not holds(changed("status"), GONE)


@pytest.mark.parametrize("p", [eq("status", "working", of="before"), one_of("status", ["working"], of="before"),
                               num("seq", 0, 99, of="before"), has("status", "w", of="before")])
def test_a_before_predicate_on_a_new_item_is_false(p: ItemPredicate) -> None:
    assert not holds(p, NEW)
    assert holds(negated(p), NEW)


@pytest.mark.parametrize("p", [eq("status", "done"), one_of("status", ["done"]), num("seq", 0, 99), has("status", "d"),
                               eq("status", "done", of="after")])
def test_an_after_predicate_on_a_gone_item_is_false(p: ItemPredicate) -> None:
    assert not holds(p, GONE)
    assert holds(negated(p), GONE)


def test_negate_inverts_each_kind() -> None:
    for p in (eq("status", "blocked"), one_of("status", ["blocked"]), num("seq", 4, 4), has("status", "bl"),
              is_new(), is_gone(), changed("seq")):
        for c in (NEW, GONE, MOVED):
            assert holds(negated(p), c) is (not holds(p, c))


@given(predicates(), changes())
def test_negate_flips_every_predicate_on_every_change(p: ItemPredicate, c: Change) -> None:
    assert holds(negated(p), c) is (not holds(p, c))


@given(predicates(), changes())
def test_a_predicate_judges_as_the_spec_reads(p: ItemPredicate, c: Change) -> None:
    assert holds(p, c) is ref_holds(p, c)


@given(predicates(), changes())
def test_a_predicate_on_a_missing_side_is_false_before_negate(p: ItemPredicate, c: Change) -> None:
    if p.kind in ("equals", "one_of", "number", "contains") and (c.before if p.of == "before" else c.after) is None:
        assert holds(negated(p) if p.negate else p, c) is False
