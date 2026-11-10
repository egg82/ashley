"""The conditions she composes a money reminder from, as a tool argument: `conditions` is a list of alternatives, each a
list of predicates that must all hold (`ashley.criteria.predicates`), and the money must satisfy one alternative. Her
parameters are hers; what she leaves out takes the default and what exceeds a limit is refused, both from
`ashley/senses/deposits.json`."""

from collections.abc import Mapping
from decimal import Decimal

from ..criteria import predicates
from ..criteria.predicates import FIELDS, KINDS, MAX_NAME, PAYEE_MATCHES, Kind, Predicate
from ..senses.deposit_config import CONFIG
from .bench_args import BadArguments

AMOUNTS = {"min_cents": "min_amount", "max_cents": "max_amount"}
"""The predicate's field in cents, and the name she gives it in the account's own currency."""

DESCRIPTION = (
    "Optional conditions the money must also meet, for what no single payee or amount says. A list of alternatives; "
    "the money counts if it meets every predicate of any one alternative. A predicate is an object with a kind and the "
    "fields of that kind, and not true to flip it. payee: text, match. amount: min_amount and/or max_amount. "
    "day_of_month: first_day to last_day. Against that payer's own deposits into the account in the last days: "
    "amount_vs_usual (above_pct over its largest, and/or below_pct under its smallest), day_vs_usual (more than "
    "tolerance_days off its usual days) and payee_new (paid fewer than min_seen times). Measured in code from the "
    "account's history, never guessed. Example, deposits from KVR off KVR's usual amount or day, or from a payer new to "
    "the account: [[payee KVR, amount_vs_usual], [payee KVR, day_vs_usual], [payee_new]].")


def schema() -> dict[str, object]:
    predicate: dict[str, object] = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "not": {"type": "boolean"},
            "text": {"type": "string", "maxLength": MAX_NAME},
            "match": {"type": "string", "enum": list(PAYEE_MATCHES)},
            "min_amount": {"type": "number", "exclusiveMinimum": 0},
            "max_amount": {"type": "number", "exclusiveMinimum": 0},
            "first_day": {"type": "integer", "minimum": 1, "maximum": 31},
            "last_day": {"type": "integer", "minimum": 1, "maximum": 31},
            "days": {"type": "integer", "minimum": 1, "maximum": CONFIG.criteria.max_days,
                     "description": f"days of history to measure against; {CONFIG.criteria.default_days} if left out"},
            "above_pct": {"type": "integer", "minimum": 0},
            "below_pct": {"type": "integer", "minimum": 0, "maximum": 99},
            "tolerance_days": {"type": "integer", "minimum": 0, "maximum": CONFIG.criteria.max_tolerance_days,
                               "description": f"{CONFIG.criteria.default_tolerance_days} if left out"},
            "min_seen": {"type": "integer", "minimum": 1,
                         "description": f"{CONFIG.criteria.default_min_seen} if left out"},
        },
        "required": ["kind"],
    }
    return {"type": "array", "description": DESCRIPTION,
            "items": {"type": "array", "minItems": 1, "items": predicate}}


def parse(raw: object) -> tuple[tuple[Predicate, ...], ...]:
    """The rule's clauses from her `conditions`. Raises BadArguments."""
    if raw is None:
        return ()
    clauses = predicates.as_list(raw)
    if clauses is None or len(clauses) > CONFIG.criteria.max_clauses:
        raise BadArguments(f"conditions is a list of at most {CONFIG.criteria.max_clauses} alternatives")
    return tuple(_clause(c) for c in clauses)


def _clause(raw: object) -> tuple[Predicate, ...]:
    items = predicates.as_list(raw)
    if items is None or not 1 <= len(items) <= CONFIG.criteria.max_predicates:
        raise BadArguments(f"an alternative is 1 to {CONFIG.criteria.max_predicates} predicates")
    return tuple(_predicate(p) for p in items)


def _kind(raw: object) -> Kind | None:
    for k in KINDS:
        if raw == k:
            return k
    return None


def _predicate(raw: object) -> Predicate:
    got = predicates.as_map(raw)
    kind = None if got is None else _kind(got.get("kind"))
    if got is None or kind is None:
        raise BadArguments(f"a predicate has a kind, one of {', '.join(KINDS)}")
    allowed = {"kind", "not", *(AMOUNTS.get(n, n) for n in FIELDS[kind])}
    if {k for k, v in got.items() if v is not None} - allowed:
        raise BadArguments(f"a {kind} predicate takes {', '.join(sorted(allowed))}")
    try:
        return predicates.from_json(_fields(kind, got))
    except ValueError as e:
        raise BadArguments(str(e)) from e


def _fields(kind: Kind, got: Mapping[str, object]) -> dict[str, object]:
    """The predicate's JSON from her arguments: amounts to cents, defaults for what she left out, limits checked."""
    c = CONFIG.criteria
    defaults: dict[str, object] = {"match": "contains", "days": c.default_days, "min_seen": c.default_min_seen, "tolerance_days": c.default_tolerance_days}
    made: dict[str, object] = {"kind": kind, "negate": got.get("not") is True}
    for name in FIELDS[kind]:
        shown = AMOUNTS.get(name, name)
        value = got.get(shown)
        made[name] = _cents(value, shown) if name in AMOUNTS else defaults.get(name) if value is None else value
    if _over(made.get("days"), c.max_days) or _over(made.get("tolerance_days"), c.max_tolerance_days):
        raise BadArguments(f"days is at most {c.max_days} and tolerance_days at most {c.max_tolerance_days}")
    return made


def _over(value: object, limit: int) -> bool:
    return type(value) is int and value > limit


def _cents(raw: object, name: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not raw > 0:
        raise BadArguments(f"{name} is a number above zero")
    return int((Decimal(str(raw)) * 100).to_integral_value())
