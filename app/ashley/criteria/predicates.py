"""The conditions she composes a rule from (`decisions.md`, "Rules she writes are composed from general
predicates"; `engineering.md`, Patterns): a closed set of typed predicate kinds, each a record of fields she sets, evaluated in code against a
transaction and, for the ones relative to history, against the other transactions the sense read. No kind is a
classification of one case; "a bonus" is whatever she composes from them.

Kinds and the fields each takes (`FIELDS`): `payee` (`text`, `match`); `amount` (`min_cents` and/or `max_cents`);
`day_of_month` (`first_day` to `last_day`, wrapping the month end when first is after last); and, against the payer's own
deposits into the same account in the last `days`: `amount_vs_usual` (true above the payer's largest by `above_pct`
percent, or below its smallest by `below_pct`), `day_vs_usual` (true when the day is more than `tolerance_days` from
every whole number of the payer's usual cadence after one of its deposits) and `payee_new` (true when it paid fewer than
`min_seen` times). A history predicate with too little history to measure is false; `negate` flips any predicate."""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from statistics import median
from typing import Any, Literal, get_args

from .record import Transaction

Kind = Literal["payee", "amount", "day_of_month", "amount_vs_usual", "day_vs_usual", "payee_new"]
KINDS: tuple[Kind, ...] = get_args(Kind)
PayeeMatch = Literal["exact", "contains"]
PAYEE_MATCHES: tuple[PayeeMatch, ...] = get_args(PayeeMatch)
MAX_NAME = 100
FIELDS: dict[Kind, tuple[str, ...]] = {
    "payee": ("text", "match"), "amount": ("min_cents", "max_cents"), "day_of_month": ("first_day", "last_day"),
    "amount_vs_usual": ("days", "above_pct", "below_pct"), "day_vs_usual": ("days", "tolerance_days"),
    "payee_new": ("days", "min_seen")}
HISTORY: tuple[Kind, ...] = ("amount_vs_usual", "day_vs_usual", "payee_new")
_OPTIONAL = {"min_cents", "max_cents", "above_pct", "below_pct"}


@dataclass(frozen=True)
class Predicate:
    kind: Kind
    negate: bool = False
    text: str | None = None
    match: PayeeMatch | None = None
    min_cents: int | None = None
    max_cents: int | None = None
    first_day: int | None = None
    last_day: int | None = None
    days: int | None = None
    above_pct: int | None = None
    below_pct: int | None = None
    tolerance_days: int | None = None
    min_seen: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"a predicate is one of {', '.join(KINDS)}")
        used = FIELDS[self.kind]
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in ("kind", "negate") or (value is not None and f.name in used):
                continue
            if value is not None:
                raise ValueError(f"a {self.kind} predicate has no {f.name}")
        missing = [n for n in used if getattr(self, n) is None and n not in _OPTIONAL]
        if missing:
            raise ValueError(f"a {self.kind} predicate needs {', '.join(missing)}")
        _check(self)


def _check(p: Predicate) -> None:
    if p.kind == "payee":
        if p.match not in PAYEE_MATCHES or not 1 <= len((p.text or "").strip()) <= MAX_NAME:
            raise ValueError(f"a payee is 1 to {MAX_NAME} characters, matched exact or contains")
    elif p.kind == "amount":
        low, high = p.min_cents, p.max_cents
        if low is None and high is None or (low or 1) <= 0 or (high or 1) <= 0 or (
                low is not None and high is not None and low > high):
            raise ValueError("an amount has a minimum, a maximum or both, above zero, the minimum not above the maximum")
    elif p.kind == "day_of_month":
        if not (1 <= (p.first_day or 0) <= 31 and 1 <= (p.last_day or 0) <= 31):
            raise ValueError("days of the month are 1 to 31")
    else:
        _check_history(p)


def _check_history(p: Predicate) -> None:
    if (p.days or 0) < 1:
        raise ValueError("days of history is at least 1")
    if p.kind == "amount_vs_usual" and (p.above_pct is None and p.below_pct is None or (p.above_pct or 0) < 0
                                        or not 0 <= (p.below_pct or 0) < 100):
        raise ValueError("an amount against the usual has above_pct, below_pct (under 100) or both")
    if p.kind == "day_vs_usual" and (p.tolerance_days or 0) < 0:
        raise ValueError("tolerance_days is not negative")
    if p.kind == "payee_new" and (p.min_seen or 0) < 1:
        raise ValueError("min_seen is at least 1")


@dataclass(frozen=True)
class History:
    """The payer's pattern in an account over a lookback, which a history predicate tests and a fired reminder carries:
    how many deposits (`seen`), their smallest and largest in cents, the median gap between them in days and the day of
    the last one. None where there were too few to measure."""

    seen: int
    low_cents: int | None = None
    high_cents: int | None = None
    every_days: int | None = None
    last_day: date | None = None


def payer(d: Transaction) -> str:
    return d.names[0].casefold() if d.names else ""


def past(deposit: Transaction, read: list[Transaction], days: int) -> list[Transaction]:
    """The payer's other counted deposits in the same account and direction dated up to `deposit`'s day, `days` back,
    oldest first."""
    return sorted((d for d in read if d.id != deposit.id and d.counts and d.direction == deposit.direction
                   and d.account_id == deposit.account_id and payer(d) == payer(deposit)
                   and 0 <= (deposit.day - d.day).days <= days), key=lambda d: d.day)


def history_of(deposit: Transaction, read: list[Transaction], days: int) -> History:
    found = past(deposit, read, days)
    if not found:
        return History(0)
    gaps = [(b.day - a.day).days for a, b in zip(found, found[1:])]
    return History(len(found), min(d.cents for d in found), max(d.cents for d in found),
                   max(1, round(median(gaps))) if gaps else None, found[-1].day)


def holds(p: Predicate, deposit: Transaction, read: list[Transaction]) -> bool:
    return _holds(p, deposit, read) != p.negate


def _holds(p: Predicate, d: Transaction, read: list[Transaction]) -> bool:
    if p.kind == "payee":
        want = (p.text or "").strip().casefold()
        return any(n.casefold() == want if p.match == "exact" else want in n.casefold() for n in d.names)
    if p.kind == "amount":
        return (p.min_cents is None or d.cents >= p.min_cents) and (p.max_cents is None or d.cents <= p.max_cents)
    if p.kind == "day_of_month":
        first, last = p.first_day or 1, p.last_day or 31
        return first <= d.day.day <= last if first <= last else d.day.day >= first or d.day.day <= last
    h = history_of(d, read, p.days or 1)
    if p.kind == "payee_new":
        return h.seen < (p.min_seen or 1)
    if p.kind == "amount_vs_usual":
        if h.low_cents is None or h.high_cents is None:
            return False
        return (p.above_pct is not None and d.cents * 100 > h.high_cents * (100 + p.above_pct)) or (
            p.below_pct is not None and d.cents * 100 < h.low_cents * (100 - p.below_pct))
    return _off_cadence(d, read, p, h)


def _off_cadence(d: Transaction, read: list[Transaction], p: Predicate, h: History) -> bool:
    if h.every_days is None:
        return False
    every = h.every_days
    return min(min(r, every - r) for r in ((d.day - o.day).days % every for o in past(d, read, p.days or 1))
               ) > (p.tolerance_days or 0)


def say(p: Predicate) -> str:
    """The predicate in words for a person's screen, built from its fields."""
    no = "not " if p.negate else ""
    if p.kind == "payee":
        return f"{no}{'the payee is' if p.match == 'exact' else 'the payee contains'} “{(p.text or '').strip()}”"
    if p.kind == "amount":
        return no + " and ".join(f"the amount is {w} {c // 100}.{c % 100:02d}" for w, c in (
            ("at least", p.min_cents), ("at most", p.max_cents)) if c is not None)
    if p.kind == "day_of_month":
        return f"{no}it is dated the {p.first_day}th to the {p.last_day}th"
    if p.kind == "payee_new":
        return f"{no}the payer paid in fewer than {p.min_seen} times in {p.days} days"
    if p.kind == "day_vs_usual":
        return f"{no}it is more than {p.tolerance_days} days off the payer's usual days (over {p.days} days)"
    sides = [f"{n}% over its largest" for n in (p.above_pct,) if n is not None] + [
        f"{n}% under its smallest" for n in (p.below_pct,) if n is not None]
    return f"{no}the amount is " + " or ".join(sides) + f" (payer's last {p.days} days)"


def to_json(p: Predicate) -> dict[str, object]:
    return {"kind": p.kind, "negate": p.negate, **{n: getattr(p, n) for n in FIELDS[p.kind]}}


def from_json(raw: Mapping[str, object]) -> Predicate:
    """Raises ValueError for anything `to_json` does not make."""
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError(f"a predicate is one of {', '.join(KINDS)}")
    names = FIELDS[kind]
    negate = raw.get("negate")
    if set(raw) != {"kind", "negate", *names} or not isinstance(negate, bool):
        raise ValueError("a predicate is its kind, negate and the fields of its kind")
    match = _text(raw, "match")
    return Predicate(kind, negate, _text(raw, "text"), "exact" if match == "exact" else "contains" if match == "contains"
                     else None, *(_whole(raw, n) for n in ("min_cents", "max_cents", "first_day", "last_day", "days",
                                                            "above_pct", "below_pct", "tolerance_days", "min_seen")))


def _text(raw: Mapping[str, object], key: str) -> str | None:
    value = raw.get(key)
    if not (value is None or isinstance(value, str)):
        raise ValueError(f"{key} is text")
    return value


def _whole(raw: Mapping[str, object], key: str) -> int | None:
    value = raw.get(key)
    if not (value is None or type(value) is int):
        raise ValueError(f"{key} is a whole number")
    return value


def history_to_json(h: History) -> dict[str, object]:
    return {"seen": h.seen, "low_cents": h.low_cents, "high_cents": h.high_cents, "every_days": h.every_days,
            "last_day": None if h.last_day is None else h.last_day.isoformat()}


def as_list(value: object) -> list[object] | None:
    """`value` as a list of objects, None when it is not a list."""
    raw: Any = value
    return list[object](raw) if isinstance(value, list) else None


def as_map(value: object) -> dict[str, object] | None:
    """`value` as an object with text keys, None when it is not one."""
    raw: Any = value
    return dict[str, object](raw) if isinstance(value, dict) else None


def history_from_json(raw: object) -> History:
    keys = {"seen", "low_cents", "high_cents", "every_days", "last_day"}
    got = as_map(raw)
    if got is None or set(got) != keys:
        raise ValueError("a history is seen, low_cents, high_cents, every_days and last_day")
    seen, low, high, every, last = (got[k] for k in ("seen", "low_cents", "high_cents", "every_days", "last_day"))
    if type(seen) is not int or not (last is None or isinstance(last, str)) \
            or any(not (n is None or type(n) is int) for n in (low, high, every)):
        raise ValueError("a history is seen, low_cents, high_cents, every_days and last_day")
    return History(seen, _opt(low), _opt(high), _opt(every), None if last is None else date.fromisoformat(last))


def _opt(value: object) -> int | None:
    return value if type(value) is int else None
