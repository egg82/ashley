"""The condition a watch ends on, as a tool argument: `until` is a list of alternatives, each a list of predicates that
must all hold (`ashley.criteria.items`), judged against what changed in one check. Its fields are enumerated from the
tracked fields of the kinds she may watch; bounds are the parser's, from `ashley/watches/watches.json`."""

from collections.abc import Collection

from ..criteria import condition, items
from ..criteria.condition import Condition
from ..criteria.items import FIELDS, KINDS, MAX_TEXT, SIDES
from ..criteria.predicates import as_list, as_map
from ..watches.config import CONFIG
from .bench_args import BadArguments

DESCRIPTION = (
    "Optional: what ends the watch, for when they want to hear about one thing and not every change. A list of "
    "alternatives; it ends when what changed meets every predicate of any one alternative, and you are told that last "
    "change. A predicate has a kind, `not` to flip it, and the fields of its kind. gone: the thing is no longer there "
    "(a session that was closed). new: it has appeared. changed: that field differs from before. equals: field is "
    "value. one_of: field is one of values. number: field is at least min and/or at most max. contains: field has "
    "text in it. equals, one_of, number and contains read the value after the change, or before it with of before. "
    "Values are text; a number is tested with number. Example, until it is closed: [[gone]].")


def schema(tracked: Collection[str]) -> dict[str, object]:
    predicate: dict[str, object] = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "not": {"type": "boolean"},
            "field": {"type": "string", "enum": sorted(tracked)},
            "value": {"type": "string", "maxLength": MAX_TEXT},
            "values": {"type": "array", "items": {"type": "string", "maxLength": MAX_TEXT}},
            "min": {"type": "number"},
            "max": {"type": "number"},
            "text": {"type": "string", "maxLength": MAX_TEXT},
            "of": {"type": "string", "enum": list(SIDES)},
        },
        "required": ["kind"],
    }
    return {"type": "array", "description": DESCRIPTION, "items": {"type": "array", "minItems": 1, "items": predicate}}


def parse(raw: object, track: tuple[str, ...]) -> Condition | None:
    """The condition from her `until`; None when she left it out. Raises BadArguments for a shape, a field outside
    `track` or a limit the settings set."""
    if raw is None:
        return None
    alternatives = as_list(raw)
    if alternatives is None:
        raise BadArguments("until is a list of alternatives, each a list of predicates")
    parsed = tuple(_alternative(a) for a in alternatives)
    try:
        condition.validate(parsed, track, CONFIG.max_alternatives, CONFIG.max_predicates)
    except ValueError as e:
        raise BadArguments(str(e)) from e
    if not parsed:
        raise BadArguments("until has at least one alternative")
    return parsed


def _alternative(raw: object) -> tuple[items.ItemPredicate, ...]:
    predicates = as_list(raw)
    if predicates is None:
        raise BadArguments("an alternative is a list of predicates")
    return tuple(_predicate(p) for p in predicates)


def _predicate(raw: object) -> items.ItemPredicate:
    got = as_map(raw)
    kind = None if got is None else got.get("kind")
    if got is None or kind not in KINDS:
        raise BadArguments(f"a predicate has a kind, one of {', '.join(KINDS)}")
    allowed = {"kind", "not", *FIELDS[kind]}
    if {k for k, v in got.items() if v is not None} - allowed:
        raise BadArguments(f"a {kind} predicate takes {', '.join(sorted(allowed))}")
    made: dict[str, object] = {"kind": kind, "negate": got.get("not") is True}
    made.update({n: got[n] for n in FIELDS[kind] if got.get(n) is not None})
    try:
        return items.from_json(made)
    except ValueError as e:
        raise BadArguments(str(e)) from e


def say(c: Condition) -> list[list[str]]:
    """The condition in words for the model and the person: its alternatives, each its predicates' words."""
    return [[items.say(p) for p in alternative] for alternative in c]
