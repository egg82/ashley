"""Pieces of the watch-items blind tests: builders for items, changes and predicates, a reference judge written from
the spec (decisions: "Watches wake her when what a read returns changes, until a condition or a time") rather than from
the code, the `claude_session` default `when`, and generators.

RECONCILED with the build (items 1-2 of the reconcile pass): Change is `Change(id, kind, before, after)`, the
predicate judge is `criteria.items.holds`, `criteria.condition.satisfied` judges a condition, `validate` lives in
`criteria.condition`, and the cut is `watches.diff.to_items`; the helpers below map the assumed names onto them.

ASSUMPTIONS (the spec leaves these open; see assumptions.txt beside the scratch notes). Change them here, nowhere else:
  A1  `ashley.criteria.items.ItemPredicate(kind, field=None, value=None, values=None, min=None, max=None, text=None,
      of="after", negate=False)`, frozen; kinds `equals one_of number contains new gone changed`.
  A2  `ashley.criteria.record.Change(identity, state, before, after)`: `state` is "new", "changed" or "gone"; `before` is
      None for new, `after` is None for gone, otherwise a mapping of tracked fields.
  A3  `ashley.criteria.items.holds(predicate, change) -> bool` (negate applied);
      `alternative_holds(alternative, change)`; `condition_holds(condition, changes) -> bool`.
      A condition is a tuple of alternatives, an alternative a tuple of ItemPredicate.
  A4  `ashley.criteria.items.validate(condition, track, max_alternatives, max_predicates)` raises ValueError.
  A5  `ashley.watches.diff.diff(before, after, max_value_chars=...) -> tuple[Change, ...]` over Items (mappings of
      identity to a mapping of tracked scalars); it returns new, changed and gone items only, in any order.
  A6  A `changed` Change carries the whole tracked mapping on both sides, not only the differing fields.
  A7  A field absent from a side's mapping is read as missing (false before negate), as is a wrong-typed value for
      `number` and `contains`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, Literal

from ashley.criteria.condition import satisfied, validate
from ashley.criteria.items import ItemPredicate, holds
from ashley.criteria.record import Change
from ashley.watches.diff import diff as built_diff
from ashley.watches.diff import to_items
from hypothesis import assume
from hypothesis import strategies as st

__all__ = ["ItemPredicate", "alternative_holds", "condition_holds", "holds", "validate", "Change", "diff"]

Scalar = str | int | float | bool | None
Items = Mapping[str, Mapping[str, Scalar]]
DEFAULT_MAX_VALUE_CHARS = 200


def alternative_holds(alternative: Sequence[ItemPredicate], change: Change) -> bool:
    return satisfied((tuple(alternative),), [change])


def condition_holds(condition: Sequence[Sequence[ItemPredicate]], changes: Sequence[Change]) -> bool:
    return satisfied(tuple(tuple(a) for a in condition), changes)


def diff(before: Items, after: Items, max_value_chars: int = DEFAULT_MAX_VALUE_CHARS) -> tuple[Change, ...]:
    """The built `diff` takes reads already cut by `to_items`; the spec's cut-then-compare is both steps."""
    return built_diff(to_items(before, max_value_chars), to_items(after, max_value_chars))
Of = Literal["before", "after"]
STATUSES = ("working", "blocked", "done", "idle")
TRACK = ("status", "seq")


def make_change(identity: str, before: Mapping[str, Scalar] | None, after: Mapping[str, Scalar] | None) -> Change:
    state = "new" if before is None else "gone" if after is None else "changed"
    return Change(identity, state, before, after)


def sess(status: str, seq: int) -> dict[str, Scalar]:
    return {"status": status, "seq": seq}


def eq(field: str, value: Scalar, of: Of = "after", negate: bool = False) -> ItemPredicate:
    return ItemPredicate("equals", field=field, value=value, of=of, negate=negate)


def one_of(field: str, values: Sequence[Scalar], of: Of = "after", negate: bool = False) -> ItemPredicate:
    return ItemPredicate("one_of", field=field, values=tuple(values), of=of, negate=negate)


def num(field: str, lo: float | None = None, hi: float | None = None, of: Of = "after",
        negate: bool = False) -> ItemPredicate:
    return ItemPredicate("number", field=field, min=lo, max=hi, of=of, negate=negate)


def has(field: str, text: str, of: Of = "after", negate: bool = False) -> ItemPredicate:
    return ItemPredicate("contains", field=field, text=text, of=of, negate=negate)


def is_new(negate: bool = False) -> ItemPredicate:
    return ItemPredicate("new", negate=negate)


def is_gone(negate: bool = False) -> ItemPredicate:
    return ItemPredicate("gone", negate=negate)


def changed(field: str, negate: bool = False) -> ItemPredicate:
    return ItemPredicate("changed", field=field, negate=negate)


def negated(p: ItemPredicate) -> ItemPredicate:
    return replace(p, negate=not p.negate)


DEFAULT_WHEN: tuple[tuple[ItemPredicate, ...], ...] = (
    (one_of("status", ["blocked", "done"]), changed("seq")),
    (eq("status", "idle"), changed("seq"), eq("status", "done", of="before", negate=True)),
)


def ref_side(p: ItemPredicate, c: Change) -> Mapping[str, Scalar] | None:
    return c.before if p.of == "before" else c.after


def ref_raw(p: ItemPredicate, c: Change) -> bool:
    """The predicate before `negate`, from the spec: a side the item lacks reads false."""
    if p.kind == "new":
        return c.kind == "new"
    if p.kind == "gone":
        return c.kind == "gone"
    if p.kind == "changed":
        if c.before is None or c.after is None:
            return False
        return c.before.get(p.field or "") != c.after.get(p.field or "")
    side = ref_side(p, c)
    if side is None or (p.field or "") not in side:
        return False
    got: Any = side[p.field or ""]
    if p.kind == "equals":
        return type(got) is type(p.value) and got == p.value
    if p.kind == "one_of":
        return any(type(got) is type(v) and got == v for v in (p.values or ()))
    if p.kind == "number":
        if isinstance(got, bool) or not isinstance(got, (int, float)):
            return False
        return (p.min is None or got >= p.min) and (p.max is None or got <= p.max)
    return isinstance(got, str) and (p.text or "").casefold() in got.casefold()


def ref_holds(p: ItemPredicate, c: Change) -> bool:
    return ref_raw(p, c) != p.negate


def ref_condition(condition: Sequence[Sequence[ItemPredicate]], changes: Sequence[Change]) -> bool:
    return any(all(ref_holds(p, c) for p in alt) for alt in condition for c in changes)


@st.composite
def tracked(draw: st.DrawFn) -> dict[str, Scalar]:
    return sess(draw(st.sampled_from(STATUSES)), draw(st.integers(0, 4)))


IDS = ("a", "b", "c", "d")


@st.composite
def item_maps(draw: st.DrawFn) -> dict[str, Mapping[str, Scalar]]:
    ids = draw(st.lists(st.sampled_from(IDS), unique=True, max_size=len(IDS)))
    return {i: draw(tracked()) for i in ids}


@st.composite
def changes(draw: st.DrawFn) -> Change:
    kind = draw(st.sampled_from(("new", "changed", "gone")))
    before = None if kind == "new" else draw(tracked())
    after = None if kind == "gone" else draw(tracked())
    if kind == "changed":
        assume(before != after)
    return make_change("a", before, after)


@st.composite
def predicates(draw: st.DrawFn) -> ItemPredicate:
    of: Of = draw(st.sampled_from(("before", "after")))
    negate = draw(st.booleans())
    kind = draw(st.sampled_from(("equals", "one_of", "number", "contains", "new", "gone", "changed")))
    if kind == "equals":
        field = draw(st.sampled_from(TRACK))
        value = draw(st.sampled_from(STATUSES)) if field == "status" else draw(st.integers(0, 4))
        return eq(field, value, of, negate)
    if kind == "one_of":
        return one_of("status", draw(st.lists(st.sampled_from(STATUSES), min_size=1, max_size=3)), of, negate)
    if kind == "number":
        lo = draw(st.one_of(st.none(), st.integers(0, 4)))
        hi = draw(st.one_of(st.none(), st.integers(0, 4))) if lo is None else draw(st.integers(lo, 4))
        if lo is None and hi is None:
            lo = 1
        return num("seq", lo, hi, of, negate)
    if kind == "contains":
        return has("status", draw(st.sampled_from(("or", "ON", "dl", "x"))), of, negate)
    if kind == "new":
        return is_new(negate)
    if kind == "gone":
        return is_gone(negate)
    return changed(draw(st.sampled_from(TRACK)), negate)


alternatives = st.lists(predicates(), min_size=1, max_size=3).map(tuple)
conditions = st.lists(alternatives, min_size=1, max_size=3).map(tuple)
