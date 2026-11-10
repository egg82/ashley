"""Pieces of the criteria blind tests: neutral transactions, a reference for the predicates written from the docs
(decisions: "Rules she writes are composed from general predicates") rather than from the code, and generators."""

from datetime import date, timedelta
from statistics import median

from ashley.criteria.predicates import History, PayeeMatch, Predicate
from ashley.criteria.record import Direction, Transaction
from ashley.senses.deposit_rule import DepositRule
from hypothesis import strategies as st
from money_support import CHECKING

ACCOUNT = CHECKING
PAYER = "KVR Payroll"
BASE = date(2026, 11, 3)


def tx(id_: str = "t0", day: date = BASE, cents: int = 100_000, payer: str | None = PAYER, account: str = ACCOUNT,
       counts: bool = True, direction: Direction = "in") -> Transaction:
    return Transaction(id_, day, account, cents, counts, () if payer is None else (payer,), direction)


def monthly(n: int, every: int = 30, cents: int = 100_000, payer: str = PAYER, end: date = BASE,
            ids: str = "h") -> list[Transaction]:
    """`n` deposits `every` days apart, the newest `every` days before `end`, oldest first."""
    return [tx(f"{ids}{i}", end - timedelta(days=every * (n - i)), cents, payer) for i in range(n)]


def rule(*clauses: tuple[Predicate, ...], min_cents: int | None = None, payee: str | None = None,
         payee_match: PayeeMatch = "contains", direction: Direction = "in", judge: bool = False) -> DepositRule:
    """A rule on the checking account with `clauses` and the other fields as given."""
    return DepositRule(ACCOUNT, "Checking", min_cents, payee, payee_match, direction, tuple(clauses), judge)


def ref_past(d: Transaction, read: list[Transaction], days: int) -> list[Transaction]:
    """The payer's other counted deposits, same account and direction, up to d's day and `days` back, oldest first."""
    out = [r for r in read if r.id != d.id and r.counts and r.account_id == d.account_id and r.direction == d.direction
           and r.names[:1] == d.names[:1] and d.day - timedelta(days=days) <= r.day <= d.day]
    return sorted(out, key=lambda r: r.day)


def ref_history(d: Transaction, read: list[Transaction], days: int) -> History:
    """Only n == 0, 1 or an even n >= 4 (an odd count of gaps, so the median is a whole day) are asserted on."""
    past = ref_past(d, read, days)
    if not past:
        return History(0)
    gaps = [(b.day - a.day).days for a, b in zip(past, past[1:])]
    every = int(median(gaps)) if len(past) >= 4 and len(past) % 2 == 0 else None
    return History(len(past), min(r.cents for r in past), max(r.cents for r in past), every, past[-1].day)


def ref_off_cadence(d: Transaction, past: list[Transaction], cadence: int, tolerance: int, first: int = 1) -> bool:
    """Off every whole cadence (`first` is the least count of them, 1) from any past deposit by more than `tolerance`."""
    for r in past:
        off = (d.day - r.day).days
        for m in range(first, off // cadence + 2):
            if abs(off - m * cadence) <= tolerance:
                return False
    return True


def ref_holds(p: Predicate, d: Transaction, read: list[Transaction]) -> bool:
    """The predicate over a read whose payer history has an even count of 4 or more or is empty (see ref_history)."""
    inner = _ref_inner(p, d, read)
    return not inner if p.negate else inner


def _ref_inner(p: Predicate, d: Transaction, read: list[Transaction]) -> bool:
    name = d.names[0].lower() if d.names else ""
    if p.kind == "payee":
        want = (p.text or "").lower()
        return name == want if p.match == "exact" else want in name
    if p.kind == "amount":
        return (p.min_cents is None or d.cents >= p.min_cents) and (p.max_cents is None or d.cents <= p.max_cents)
    if p.kind == "day_of_month":
        return (p.first_day or 1) <= d.day.day <= (p.last_day or 31)
    days = p.days or 120
    past = ref_past(d, read, days)
    if p.kind == "payee_new":
        return len(past) < (p.min_seen or 2)
    if not past:
        return False
    if p.kind == "amount_vs_usual":
        high, low = max(r.cents for r in past), min(r.cents for r in past)
        above = p.above_pct is not None and d.cents * 100 > high * (100 + p.above_pct)
        below = p.below_pct is not None and d.cents * 100 < low * (100 - p.below_pct)
        return above or below
    h = ref_history(d, read, days)
    if h.every_days is None:
        return False
    return ref_off_cadence(d, past, h.every_days, p.tolerance_days if p.tolerance_days is not None else 3)


def payee(text: str = "KVR", match: PayeeMatch = "contains", negate: bool = False) -> Predicate:
    return Predicate("payee", negate, text=text, match=match)


def amount(lo: int | None = None, hi: int | None = None, negate: bool = False) -> Predicate:
    return Predicate("amount", negate, min_cents=lo, max_cents=hi)


def above(pct: int = 20, days: int = 120, negate: bool = False) -> Predicate:
    return Predicate("amount_vs_usual", negate, days=days, above_pct=pct)


def below(pct: int = 20, days: int = 120, negate: bool = False) -> Predicate:
    return Predicate("amount_vs_usual", negate, days=days, below_pct=pct)


def off_day(tolerance: int = 3, days: int = 120, negate: bool = False) -> Predicate:
    return Predicate("day_vs_usual", negate, days=days, tolerance_days=tolerance)


def new_payer(min_seen: int = 2, days: int = 120, negate: bool = False) -> Predicate:
    return Predicate("payee_new", negate, days=days, min_seen=min_seen)


def window(first: int, last: int, negate: bool = False) -> Predicate:
    return Predicate("day_of_month", negate, first_day=first, last_day=last)


def predicates(kinds: tuple[str, ...] = ()) -> st.SearchStrategy[Predicate]:
    """Every kind (or only `kinds`) with the fields its kind uses."""
    chosen = [b for k, b in _builders() if not kinds or k in kinds]
    return st.one_of(*chosen)


def _builders() -> list[tuple[str, st.SearchStrategy[Predicate]]]:
    flag = st.booleans()
    return [
        ("payee", st.builds(Predicate, kind=st.just("payee"), negate=flag,
                            text=st.text(st.characters(categories=["Lu", "Ll", "Nd"]), min_size=1, max_size=20),
                            match=st.sampled_from(["exact", "contains"]))),
        ("amount", st.builds(Predicate, kind=st.just("amount"), negate=flag, min_cents=st.integers(1, 10**8),
                             max_cents=st.none())),
        ("amount", st.builds(Predicate, kind=st.just("amount"), negate=flag, min_cents=st.none(),
                             max_cents=st.integers(1, 10**8))),
        ("amount", st.builds(Predicate, kind=st.just("amount"), negate=flag, min_cents=st.integers(1, 100),
                             max_cents=st.integers(101, 10**8))),
        ("day_of_month", st.builds(Predicate, kind=st.just("day_of_month"), negate=flag, first_day=st.integers(1, 15),
                                   last_day=st.integers(16, 31))),
        ("amount_vs_usual", st.builds(Predicate, kind=st.just("amount_vs_usual"), negate=flag, days=st.integers(1, 365),
                                      above_pct=st.integers(0, 500), below_pct=st.none())),
        ("amount_vs_usual", st.builds(Predicate, kind=st.just("amount_vs_usual"), negate=flag, days=st.integers(1, 365),
                                      above_pct=st.none(), below_pct=st.integers(0, 99))),
        ("amount_vs_usual", st.builds(Predicate, kind=st.just("amount_vs_usual"), negate=flag, days=st.integers(1, 365),
                                      above_pct=st.integers(0, 500), below_pct=st.integers(0, 99))),
        ("day_vs_usual", st.builds(Predicate, kind=st.just("day_vs_usual"), negate=flag, days=st.integers(1, 365),
                                   tolerance_days=st.integers(0, 15))),
        ("payee_new", st.builds(Predicate, kind=st.just("payee_new"), negate=flag, days=st.integers(1, 365),
                                min_seen=st.integers(1, 20)))]
