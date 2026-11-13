"""The money rule `remind_on_money`'s arguments give (`ashley.tools.reminders`), checked field by field; a bad one
raises BadArguments, and the rule's own checks raise ValueError."""

from collections.abc import Mapping
from decimal import Decimal

from ..senses.deposit_rule import PAYEE_MATCHES, DepositRule, Direction, PayeeMatch
from . import reminder_conditions as conditions
from .bench_args import BadArguments


def rule_of(args: Mapping[str, object]) -> DepositRule:
    return DepositRule(_text(args, "account_id"), _text(args, "account"), _cents(args.get("min_amount")),
                       _payee(args.get("payee")), _match(args.get("payee_match")),
                       _direction(args.get("direction")), conditions.parse(args.get("conditions")),
                       args.get("judge") is True)


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
    raise BadArguments("direction is in or out")
