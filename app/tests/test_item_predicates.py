"""Item predicates (`ashley.criteria.items`) judge one `Change` from its tracked fields, a missing side is false before
`negate`, and a condition (`ashley.criteria.condition`) holds when some changed item satisfies an alternative."""

from typing import Any

import pytest
from ashley.criteria import condition, items
from ashley.criteria.items import ItemPredicate
from ashley.criteria.record import Change, ChangeKind


def ch(kind: ChangeKind, before: dict[str, Any] | None, after: dict[str, Any] | None) -> Change:
    return Change("s1", kind, before, after)


NEW = ch("new", None, {"status": "done", "seq": 3})
GONE = ch("gone", {"status": "done", "seq": 3}, None)
MOVED = ch("changed", {"status": "working", "seq": 3}, {"status": "blocked", "seq": 4})


def test_each_kind_reads_its_side() -> None:
    assert items.holds(ItemPredicate("equals", field="status", value="blocked"), MOVED)
    assert not items.holds(ItemPredicate("equals", field="status", value="blocked", of="before"), MOVED)
    assert items.holds(ItemPredicate("equals", field="status", value="working", of="before"), MOVED)
    assert items.holds(ItemPredicate("one_of", field="status", values=("done", "blocked")), MOVED)
    assert items.holds(ItemPredicate("number", field="seq", min=4), MOVED)
    assert not items.holds(ItemPredicate("number", field="seq", min=5), MOVED)
    assert items.holds(ItemPredicate("number", field="seq", max=3, of="before"), MOVED)
    assert items.holds(ItemPredicate("contains", field="status", text="LOCK"), MOVED)
    assert items.holds(ItemPredicate("changed", field="seq"), MOVED)
    assert not items.holds(ItemPredicate("changed", field="seq"), ch("changed", {"seq": 1, "x": 1}, {"seq": 1, "x": 2}))
    assert items.holds(ItemPredicate("new"), NEW) and not items.holds(ItemPredicate("new"), MOVED)
    assert items.holds(ItemPredicate("gone"), GONE) and not items.holds(ItemPredicate("gone"), NEW)


def test_a_missing_side_is_false_before_negate() -> None:
    before_new = ItemPredicate("equals", field="status", value="done", of="before")
    assert not items.holds(before_new, NEW)
    assert items.holds(ItemPredicate("equals", field="status", value="done", of="before", negate=True), NEW)
    assert not items.holds(ItemPredicate("equals", field="status", value="done"), GONE)
    assert not items.holds(ItemPredicate("changed", field="seq"), NEW)
    assert items.holds(ItemPredicate("changed", field="seq", negate=True), GONE)
    assert not items.holds(ItemPredicate("equals", field="nope", value="x"), MOVED)


def test_types_do_not_blur() -> None:
    flag = ch("changed", {"on": False, "n": 1}, {"on": True, "n": 1.0})
    assert not items.holds(ItemPredicate("equals", field="on", value=1), flag)
    assert items.holds(ItemPredicate("equals", field="on", value=True), flag)
    assert not items.holds(ItemPredicate("number", field="on", min=0), flag)
    assert items.holds(ItemPredicate("equals", field="n", value=1), flag)
    assert not items.holds(ItemPredicate("changed", field="n"), flag)
    assert not items.holds(ItemPredicate("contains", field="n", text="1"), flag)


@pytest.mark.parametrize("given", [
    {"kind": "shout"}, {"kind": "equals", "field": "a"}, {"kind": "equals", "value": "x"},
    {"kind": "equals", "field": "a", "value": None}, {"kind": "new", "field": "a"}, {"kind": "new", "of": "before"},
    {"kind": "equals", "field": "a", "value": "x", "of": "then"}, {"kind": "one_of", "field": "a", "values": ()},
    {"kind": "number", "field": "a"}, {"kind": "number", "field": "a", "min": 3, "max": 2},
    {"kind": "number", "field": "a", "min": True}, {"kind": "number", "field": "a", "min": float("nan")},
    {"kind": "contains", "field": "a", "text": " "}, {"kind": "contains", "field": "a", "text": "x", "value": "y"},
    {"kind": "one_of", "field": "a", "values": tuple(range(21))}])
def test_a_malformed_predicate_is_refused(given: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ItemPredicate(**given)


def test_json_round_trips_and_refuses_strangers() -> None:
    every = [ItemPredicate("equals", field="a", value=2.5, of="before"), ItemPredicate("one_of", True, "a", values=("x", 1)),
             ItemPredicate("number", field="a", max=2), ItemPredicate("contains", field="a", text="t"),
             ItemPredicate("new"), ItemPredicate("gone", True), ItemPredicate("changed", field="a")]
    for p in every:
        assert items.from_json(items.to_json(p)) == p
    assert items.from_json({"kind": "equals", "negate": False, "field": "a", "value": "x"}).of == "after"
    for bad in ({"kind": "new"}, {"kind": "new", "negate": False, "field": "a"}, {"kind": "equals", "negate": False, "field": "a"},
                {"kind": "one_of", "negate": False, "field": "a", "values": "xy"}, {"kind": "number", "negate": False, "field": "a", "min": "1"},
                {"kind": "equals", "negate": False, "field": "a", "value": [1]}):
        with pytest.raises(ValueError):
            items.from_json(bad)


def test_say_names_the_fields() -> None:
    assert items.say(ItemPredicate("equals", True, "status", value="done", of="before")) == "not status before is done"
    assert items.say(ItemPredicate("number", field="seq", min=1, max=2)) == "seq is at least 1 and seq is at most 2"


DEFAULT = (
    (ItemPredicate("one_of", field="status", values=("blocked", "done")), ItemPredicate("changed", field="seq")),
    (ItemPredicate("equals", field="status", value="idle"), ItemPredicate("changed", field="seq"),
     ItemPredicate("equals", True, "status", value="done", of="before")))


def test_a_condition_holds_when_some_changed_item_meets_an_alternative() -> None:
    finished = ch("changed", {"status": "working", "seq": 3}, {"status": "done", "seq": 4})
    seen = ch("changed", {"status": "done", "seq": 4}, {"status": "idle", "seq": 5})
    other = ch("changed", {"status": "blocked", "seq": 4}, {"status": "idle", "seq": 5})
    assert condition.satisfied(DEFAULT, [finished])
    assert not condition.satisfied(DEFAULT, [seen])
    assert condition.satisfied(DEFAULT, [seen, other])
    assert not condition.satisfied(DEFAULT, [])
    assert not condition.satisfied((), [finished])


def test_an_alternative_needs_all_its_predicates_on_one_item() -> None:
    a = ch("changed", {"status": "x", "seq": 1}, {"status": "done", "seq": 1})
    b = ch("changed", {"status": "x", "seq": 1}, {"status": "x", "seq": 2})
    assert not condition.satisfied(DEFAULT[:1], [a, b])


def test_validate_refuses_untracked_fields_and_over_limits() -> None:
    condition.validate(DEFAULT, ("status", "seq"), 2, 3)
    condition.validate(((ItemPredicate("new"),),), (), 1, 1)
    with pytest.raises(ValueError, match="label"):
        condition.validate(((ItemPredicate("equals", field="label", value="x"),),), ("status", "seq"), 2, 3)
    with pytest.raises(ValueError, match="alternatives"):
        condition.validate(DEFAULT, ("status", "seq"), 1, 3)
    with pytest.raises(ValueError, match="predicates"):
        condition.validate(DEFAULT, ("status", "seq"), 2, 2)
    with pytest.raises(ValueError, match="predicates"):
        condition.validate(((),), ("status",), 2, 2)


def test_a_condition_survives_json() -> None:
    assert condition.from_json(condition.to_json(DEFAULT)) == DEFAULT
    assert condition.from_json([]) == ()
    for bad in ("x", [1], [["x"]], {"a": 1}):
        with pytest.raises(ValueError):
            condition.from_json(bad)
