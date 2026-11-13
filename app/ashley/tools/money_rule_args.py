"""The money rule `remind_on_money`'s arguments give (`ashley.tools.reminders`), checked field by field; a bad one
raises BadArguments, and the rule's own checks raise ValueError."""

from collections.abc import Mapping
from decimal import Decimal

from ..senses.deposit_config import CONFIG
from ..senses.deposit_rule import PAYEE_MATCHES, DepositRule, Direction, PayeeMatch
from . import reminder_conditions as conditions
from .bench_args import BadArguments


def rule_of(args: Mapping[str, object]) -> DepositRule:
    """On money moving `direction`, a balance falling below `balance_below`, or a bill coming due `bill_due_days` ahead:
    exactly one of the three."""
    below, due = args.get("balance_below"), args.get("bill_due_days")
    if sum(v is not None for v in (below, due, args.get("direction"))) != 1:
        raise BadArguments("give exactly one of direction (money moving), balance_below or bill_due_days")
    account, name = _text(args, "account_id"), _text(args, "account")
    if due is not None:
        return DepositRule(account, name, _cents(args.get("min_amount")), _payee(args.get("payee")),
                           _match(args.get("payee_match")), clauses=conditions.parse(args.get("conditions")),
                           judge=args.get("judge") is True, due_days=_days(due))
    if below is not None:
        if isinstance(below, bool) or not isinstance(below, int | float):
            raise BadArguments("balance_below is an amount")
        return DepositRule(account, name, _cents(args.get("min_amount")), _payee(args.get("payee")),
                           clauses=conditions.parse(args.get("conditions")), judge=args.get("judge") is True,
                           below_cents=int((Decimal(str(below)) * 100).to_integral_value()))
    return DepositRule(account, name, _cents(args.get("min_amount")), _payee(args.get("payee")),
                       _match(args.get("payee_match")), _direction(args.get("direction")),
                       conditions.parse(args.get("conditions")), args.get("judge") is True)


def _days(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= CONFIG.max_due_days:
        raise BadArguments(f"bill_due_days is a whole number of days from 0 to {CONFIG.max_due_days}")
    return raw


def _text(args: Mapping[str, object], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BadArguments(f"{key} is as Sure shows it")
    return value.strip()


def _cents(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not raw > 0:
        raise BadArguments("min_amount is a number above zero")
    return int((Decimal(str(raw)) * 100).to_integral_value())


def _payee(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise BadArguments("payee is a name as Sure shows it")
    return raw


def _match(raw: object) -> PayeeMatch:
    if raw is None:
        return "contains"
    if raw not in PAYEE_MATCHES:
        raise BadArguments("payee_match is exact or contains")
    return "exact" if raw == "exact" else "contains"


def _direction(raw: object) -> Direction:
    if raw == "in":
        return "in"
    if raw == "out":
        return "out"
    raise BadArguments("direction is in or out, or give balance_below or bill_due_days instead")
