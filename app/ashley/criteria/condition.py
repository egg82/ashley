"""A watch's `when` or `until`: a list of alternatives, each a list of `ItemPredicate`s that must all hold, any one
alternative being enough (the clause shape of the money rules). Judged over the changes of one check, and refused at
arming when it reads an untracked field or exceeds its limits."""

from collections.abc import Collection, Iterable, Mapping

from . import items
from .items import ItemPredicate
from .predicates import as_list, as_map
from .record import Change

Condition = tuple[tuple[ItemPredicate, ...], ...]


def satisfied(condition: Condition, changes: Iterable[Change]) -> bool:
    """Whether some change satisfies some alternative. Items that did not change are not in `changes`, so are never
    judged; no changes, or no alternatives, is False."""
    return any(all(items.holds(p, c) for p in alternative) for c in changes for alternative in condition)


def validate(condition: Condition, track: Collection[str], max_alternatives: int, max_predicates: int) -> None:
    """Raises ValueError, naming what is wrong, for an empty alternative, a `field` outside `track`, more than
    `max_alternatives` alternatives, or more than `max_predicates` predicates in one."""
    if len(condition) > max_alternatives:
        raise ValueError(f"a condition has at most {max_alternatives} alternatives, not {len(condition)}")
    for alternative in condition:
        if not 1 <= len(alternative) <= max_predicates:
            raise ValueError(f"an alternative is 1 to {max_predicates} predicates, not {len(alternative)}")
        for p in alternative:
            if p.field is not None and p.field not in track:
                raise ValueError(f"{p.field} is not a tracked field; the tracked fields are {', '.join(track)}")


def to_json(condition: Condition) -> list[list[dict[str, object]]]:
    return [[items.to_json(p) for p in alternative] for alternative in condition]


def from_json(raw: object) -> Condition:
    """Raises ValueError for anything `to_json` does not make."""
    alternatives = [as_list(a) for a in as_list(raw) or []]
    if as_list(raw) is None or any(a is None for a in alternatives):
        raise ValueError("a condition is a list of alternatives, each a list of predicates")
    return tuple(tuple(items.from_json(_map(p)) for p in a or []) for a in alternatives)


def _map(raw: object) -> Mapping[str, object]:
    got = as_map(raw)
    if got is None:
        raise ValueError("a predicate is an object")
    return got
