"""What changed between two reads of a watch. `Items` is one read: a map from an item's identity to its tracked scalar
fields (`to_items` makes one from raw values). `diff` turns the baseline and a later read into the `Change`s, in
identity order."""

from collections.abc import Mapping
from math import isfinite

from ..criteria.record import Change, Fields, Scalar, differs
from ..text import without_nul

Items = Mapping[str, Fields]


def scalar(value: object, max_value_chars: int) -> Scalar:
    """A tracked value: text cut to `max_value_chars`, a number, a boolean or None. Raises ValueError for anything
    else, and for a number that is not finite."""
    if isinstance(value, str):
        return value[:max_value_chars]
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) or (isinstance(value, float) and isfinite(value)):
        return value
    raise ValueError("a tracked field is text, a number, true, false or null")


def to_items(raw: Mapping[str, Mapping[str, object]], max_value_chars: int) -> Items:
    """A read as items, its text cleaned of NULs, which no jsonb holds."""
    return {without_nul(i, "watch"): {k: scalar(_clean(v), max_value_chars) for k, v in fields.items()}
            for i, fields in raw.items()}


def _clean(value: object) -> object:
    return without_nul(value, "watch") if isinstance(value, str) else value


def diff(before: Items, after: Items) -> tuple[Change, ...]:
    """The items new in `after`, gone from it, or with a tracked field that differs, sorted by identity."""
    out: list[Change] = []
    for i in sorted(before.keys() | after.keys()):
        old, new = before.get(i), after.get(i)
        if old is None and new is not None:
            out.append(Change(i, "new", None, new))
        elif new is None and old is not None:
            out.append(Change(i, "gone", old, None))
        elif old is not None and new is not None and differs(old, new):
            out.append(Change(i, "changed", old, new))
    return tuple(out)
