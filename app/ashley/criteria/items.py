"""The conditions she composes a watch from (`decisions.md`, "Watches wake her when what a read returns changes"): a
closed set of typed predicate kinds, each a record of fields she sets, judged in code against one `Change`. Sibling of
`predicates`, which reads a transaction; these read an item's tracked fields before and after a change.

Kinds and the fields each takes (`FIELDS`): `equals` (`field`, `value`), `one_of` (`field`, `values`), `number`
(`field`, `min` and/or `max`) and `contains` (`field`, `text`, case-insensitive), each read after the change or, with
`of` `before`, before it; `new`, `gone`, and `changed` (`field`, true when that field differs). A predicate that reads a
side the item lacks, or a field or type it does not have, is false; `negate` then flips it. Bounds on a whole condition
are the parser's (`condition`)."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from math import isfinite
from typing import Literal, TypeGuard, get_args

from .predicates import as_list
from .record import Change, Scalar, same

Kind = Literal["equals", "one_of", "number", "contains", "new", "gone", "changed"]
KINDS: tuple[Kind, ...] = get_args(Kind)
Side = Literal["before", "after"]
SIDES: tuple[Side, ...] = get_args(Side)
MAX_TEXT = 200
MAX_VALUES = 20
FIELDS: dict[Kind, tuple[str, ...]] = {
    "equals": ("field", "value", "of"), "one_of": ("field", "values", "of"), "number": ("field", "min", "max", "of"),
    "contains": ("field", "text", "of"), "new": (), "gone": (), "changed": ("field",)}
_OPTIONAL = {"min", "max", "of"}


@dataclass(frozen=True)
class ItemPredicate:
    kind: Kind
    negate: bool = False
    field: str | None = None
    value: Scalar = None
    values: tuple[Scalar, ...] | None = None
    min: int | float | None = None
    max: int | float | None = None
    text: str | None = None
    of: Side = "after"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"a predicate is one of {', '.join(KINDS)}")
        used = FIELDS[self.kind]
        for f in fields(self):
            if f.name not in ("kind", "negate", "of") and getattr(self, f.name) is not None and f.name not in used:
                raise ValueError(f"a {self.kind} predicate has no {f.name}")
        if self.of != "after" and "of" not in used:
            raise ValueError(f"a {self.kind} predicate has no of")
        missing = [n for n in used if getattr(self, n) is None and n not in _OPTIONAL]
        if missing:
            raise ValueError(f"a {self.kind} predicate needs {', '.join(missing)}")
        _check(self)


def _check(p: ItemPredicate) -> None:
    if p.of not in SIDES:
        raise ValueError("of is before or after")
    if p.field is not None and not 1 <= len(p.field) <= MAX_TEXT:
        raise ValueError(f"a field name is 1 to {MAX_TEXT} characters")
    if p.kind == "equals" and not _scalar(p.value):
        raise ValueError(f"a value is text up to {MAX_TEXT} characters, a number or true or false")
    if p.kind == "one_of" and not (p.values and len(p.values) <= MAX_VALUES and all(_scalar(v) for v in p.values)):
        raise ValueError(f"values is 1 to {MAX_VALUES} texts, numbers or booleans")
    if p.kind == "contains" and not 1 <= len((p.text or "").strip()) <= MAX_TEXT:
        raise ValueError(f"text is 1 to {MAX_TEXT} characters")
    if p.kind == "number":
        low, high = p.min, p.max
        if low is None and high is None or not all(_real(n) for n in (low, high) if n is not None) or (
                low is not None and high is not None and low > high):
            raise ValueError("a number has a minimum, a maximum or both, the minimum not above the maximum")


def _real(n: object) -> TypeGuard[int | float]:
    return isinstance(n, int | float) and not isinstance(n, bool) and isfinite(n)


def _scalar(v: object) -> bool:
    return v is not None and (_real(v) or isinstance(v, bool) or (isinstance(v, str) and len(v) <= MAX_TEXT))


def holds(p: ItemPredicate, change: Change) -> bool:
    return _holds(p, change) != p.negate


def _holds(p: ItemPredicate, c: Change) -> bool:
    if p.kind in ("new", "gone"):
        return c.kind == p.kind
    if p.kind == "changed":
        return _changed(p, c)
    side = c.before if p.of == "before" else c.after
    name = p.field or ""
    return side is not None and name in side and _read(p, side[name])


def _changed(p: ItemPredicate, c: Change) -> bool:
    name = p.field or ""
    if c.before is None or c.after is None or name not in c.before or name not in c.after:
        return False
    return not same(c.before[name], c.after[name])


def _read(p: ItemPredicate, got: Scalar) -> bool:
    if p.kind == "equals":
        return same(got, p.value)
    if p.kind == "one_of":
        return any(same(got, v) for v in p.values or ())
    if p.kind == "contains":
        return isinstance(got, str) and (p.text or "").strip().casefold() in got.casefold()
    if not _real(got):
        return False
    return (p.min is None or got >= p.min) and (p.max is None or got <= p.max)


def say(p: ItemPredicate) -> str:
    """The predicate in words for a person's screen, built from its fields."""
    no = "not " if p.negate else ""
    when = " before" if p.of == "before" else ""
    if p.kind in ("new", "gone"):
        return f"{no}the item is {p.kind}"
    if p.kind == "changed":
        return f"{no}{p.field} changed"
    if p.kind == "equals":
        return f"{no}{p.field}{when} is {p.value}"
    if p.kind == "one_of":
        return f"{no}{p.field}{when} is one of {', '.join(str(v) for v in p.values or ())}"
    if p.kind == "contains":
        return f"{no}{p.field}{when} contains “{(p.text or '').strip()}”"
    return no + " and ".join(f"{p.field}{when} is {w} {n}" for w, n in (("at least", p.min), ("at most", p.max))
                             if n is not None)


def to_json(p: ItemPredicate) -> dict[str, object]:
    made: dict[str, object] = {"kind": p.kind, "negate": p.negate}
    for n in FIELDS[p.kind]:
        v = getattr(p, n)
        made[n] = list(v) if n == "values" else v
    return made


def from_json(raw: Mapping[str, object]) -> ItemPredicate:
    """Raises ValueError for anything `to_json` does not make."""
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"a predicate is one of {', '.join(KINDS)}")
    names = FIELDS[kind]
    negate = raw.get("negate")
    if not {"kind", "negate", *(n for n in names if n not in _OPTIONAL)} <= set(raw) <= {"kind", "negate", *names} \
            or not isinstance(negate, bool):
        raise ValueError("a predicate is its kind, negate and the fields of its kind")
    values = as_list(raw.get("values"))
    if values is None and raw.get("values") is not None:
        raise ValueError("values is a list")
    of = raw.get("of", "after")
    if of not in SIDES:
        raise ValueError("of is before or after")
    return ItemPredicate(kind, negate, _text(raw, "field"), _scalar_of(raw.get("value")),
                         None if values is None else tuple(_scalar_of(v) for v in values), _num(raw.get("min")),
                         _num(raw.get("max")), _text(raw, "text"), of)


def _text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if not (value is None or isinstance(value, str)):
        raise ValueError(f"{key} is text")
    return value


def _num(value: object) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("min and max are numbers")
    return value


def _scalar_of(value: object) -> Scalar:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError("a value is text, a number or true or false")
