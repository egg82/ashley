"""Shared fixtures of the money-conditions suite: the payroll history of the live defect (KVR about 8700 monthly on the
5th, interest monthly) and the predicates she composes for it."""

from datetime import date

from ashley.criteria.predicates import Predicate
from ashley.criteria.record import Transaction

ACCOUNT = "acct-checking"


def tx(id_: str, name: str, cents: int, day: date, *, counts: bool = True, account: str = ACCOUNT) -> Transaction:
    return Transaction(id_, day, account, cents, counts, (name,))


def history() -> list[Transaction]:
    paychecks = [tx(f"p{m}", "KVR INC", 870_000, date(2026, m, 5)) for m in (7, 8, 9, 10)]
    interest = [tx(f"i{m}", "INTEREST", 412, date(2026, m, 28)) for m in (8, 9, 10)]
    return paychecks + interest


def payee(text: str) -> Predicate:
    return Predicate("payee", text=text, match="contains")


def amount_off() -> Predicate:
    return Predicate("amount_vs_usual", days=120, above_pct=25, below_pct=25)


def day_off() -> Predicate:
    return Predicate("day_vs_usual", days=120, tolerance_days=3)


def new_payer() -> Predicate:
    return Predicate("payee_new", days=120, min_seen=2)


def composed() -> tuple[tuple[Predicate, ...], ...]:
    """KVR deposits off KVR's usual amount or day, or any deposit from a payer new to the account."""
    return ((payee("KVR"), amount_off()), (payee("KVR"), day_off()), (new_payer(),))
