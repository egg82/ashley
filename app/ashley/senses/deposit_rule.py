"""What an event reminder waits for, as fields she sets, never her words: money moving `direction` (`in`, a deposit into,
or `out`, a withdrawal from) `account_id` (as Sure identifies it; `account_name` is only how Sure names it, for showing
the rule), of at least `min_cents` when given, with a payee Sure names, `payee`, equal to it or containing it
(`payee_match`) when given, and, when `clauses` are given, one of them holding: each a list of predicates that must all
hold (`deposit_predicates`), so she composes what she waits for from general conditions, the history ones measured in
code. With `judge` the fired reminder lets her stay quiet on a match that is not what the person meant. With
`below_cents` the rule waits instead on the account's balance falling below that many minor units (signed as the ledger
signs it), and has no minimum, payee or clauses, which describe a transaction. Matching compares those fields to the transaction's own and reads no prose. The module and
its `Deposit`/`DepositRule` keep the name they had when only deposits could be waited on."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from ..criteria import predicates
from ..criteria.predicates import HISTORY, MAX_NAME, PAYEE_MATCHES, History, PayeeMatch, Predicate
from ..criteria.record import DIRECTIONS, Direction
from ..criteria.record import Transaction as Deposit

Clause = tuple[Predicate, ...]


@dataclass(frozen=True)
class DepositRule:
    account_id: str
    account_name: str
    min_cents: int | None = None
    payee: str | None = None
    payee_match: PayeeMatch = "contains"
    direction: Direction = "in"
    clauses: tuple[Clause, ...] = ()
    judge: bool = False
    below_cents: int | None = None

    def history_days(self, judged: int) -> int | None:
        """How many days of the payer's history a match needs: the longest a predicate asks, or at least `judged` when
        she judges the fire; None when nothing reads history."""
        asked = [p.days or 0 for c in self.clauses for p in c if p.kind in HISTORY]
        return max([judged, *asked]) if self.judge else max(asked, default=None)

    def __post_init__(self) -> None:
        if not 1 <= len(self.account_id) <= MAX_NAME or not 1 <= len(self.account_name) <= MAX_NAME:
            raise ValueError(f"the account is named and identified in 1 to {MAX_NAME} characters")
        if self.below_cents is not None and (self.min_cents is not None or self.payee is not None or self.clauses):
            raise ValueError("a balance rule has no minimum amount, payee or conditions")
        if self.below_cents is None and self.min_cents is None and self.payee is None and not self.clauses:
            raise ValueError("a rule needs a minimum amount, a payee, conditions, or a mix, or a balance to fall below")
        if any(not c for c in self.clauses):
            raise ValueError("a clause has at least one predicate")
        if self.min_cents is not None and self.min_cents <= 0:
            raise ValueError("the minimum amount is above zero")
        if self.payee is not None and not 1 <= len(self.payee.strip()) <= MAX_NAME:
            raise ValueError(f"the payee is 1 to {MAX_NAME} characters")
        if self.payee_match not in PAYEE_MATCHES:
            raise ValueError("payee_match is exact or contains")
        if self.direction not in DIRECTIONS:
            raise ValueError("direction is in or out")


@dataclass(frozen=True)
class Landed:
    """The transaction a reminder fired for, as fields: `cents` unsigned, the `day` it is dated, the `account_name` of the
    rule it matched, `payee`, the first name Sure gives it (merchant, then its own name), None when it gives none, and
    whether it came `in` or went `out`. `because` is the kinds of the predicates of the clause that held, `history` the
    payer's pattern when the rule reads it, and `judged` that the rule lets her stay quiet on it. For a balance that
    fell below a rule's `below_cents`, `below_cents` is that threshold, `cents` the balance (signed), `day` the day it
    was read, and there is no payee."""

    cents: int
    day: date
    account_name: str
    payee: str | None
    direction: Direction = "in"
    because: tuple[str, ...] = ()
    history: History | None = None
    judged: bool = False
    below_cents: int | None = None


def landed(rule: DepositRule, deposit: Deposit, read: list[Deposit] | None = None, judged_days: int = 0) -> Landed:
    """What a match stores; `read` is every transaction the sense read, `judged_days` the history a judged fire carries."""
    days = rule.history_days(judged_days)
    known = [] if read is None else read
    clause = _holding(rule, deposit, known)
    return Landed(deposit.cents, deposit.day, rule.account_name, deposit.names[0] if deposit.names else None,
                  deposit.direction, tuple(("not " if p.negate else "") + p.kind for p in clause or ()),
                  None if days is None else predicates.history_of(deposit, known, days), rule.judge)


def _holding(rule: DepositRule, deposit: Deposit, read: list[Deposit]) -> Clause | None:
    """The first clause whose predicates all hold, None when there is none or the rule has no clauses."""
    return next((c for c in rule.clauses if all(predicates.holds(p, deposit, read) for p in c)), None)


def landed_to_json(landed: Landed) -> dict[str, object]:
    return {"cents": landed.cents, "day": landed.day.isoformat(), "account_name": landed.account_name,
            "payee": landed.payee, "direction": landed.direction, "because": list(landed.because),
            "history": None if landed.history is None else predicates.history_to_json(landed.history),
            "judged": landed.judged, **({} if landed.below_cents is None else {"below_cents": landed.below_cents})}


def landed_from_json(raw: Mapping[str, object]) -> Landed:
    """Raises ValueError for anything `landed_to_json` does not make; one stored before `direction` existed is `in`."""
    cents, day, account, payee, way = (raw.get(k) for k in ("cents", "day", "account_name", "payee", "direction"))
    base = {"cents", "day", "account_name", "payee"}
    extra = {"direction", "because", "history", "judged", "below_cents"}
    because, judged = predicates.as_list(raw.get("because", [])), raw.get("judged", False)
    below = raw.get("below_cents")
    if not base <= set(raw) <= base | extra or type(judged) is not bool or because is None \
            or not (below is None or type(below) is int) \
            or any(not isinstance(b, str) for b in because) or type(cents) is not int or not isinstance(day, str) \
            or not isinstance(account, str) or not (payee is None or isinstance(payee, str)) \
            or way not in (None, *DIRECTIONS):
        raise ValueError("a landed transaction is cents, day, account_name, payee and direction")
    history = raw.get("history")
    return Landed(cents, date.fromisoformat(day), account, payee, "out" if way == "out" else "in",
                  tuple(str(b) for b in because), None if history is None else predicates.history_from_json(history),
                  judged, below)


def matches(rule: DepositRule, deposit: Deposit, since: date, read: list[Deposit] | None = None) -> bool:
    """Whether `deposit` is one the rule waits for: dated on or after `since` (the day the rule was set), counted, going
    the rule's way in its account, at least its minimum, with its payee, and, when it has clauses, one holding against
    `read`, the transactions the sense read (the history ones are false without them). A balance rule matches none."""
    if rule.below_cents is not None or not deposit.counts or deposit.day < since or deposit.account_id != rule.account_id \
            or deposit.direction != rule.direction:
        return False
    if rule.min_cents is not None and deposit.cents < rule.min_cents:
        return False
    if rule.clauses and _holding(rule, deposit, [] if read is None else read) is None:
        return False
    if rule.payee is None:
        return True
    want = rule.payee.strip().casefold()
    return any(name.casefold() == want if rule.payee_match == "exact" else want in name.casefold()
               for name in deposit.names)


def describe(rule: DepositRule) -> str:
    """The rule in words for a person's screen, built from its fields."""
    if rule.below_cents is not None:
        return f"the balance of {rule.account_name} falling below {money(rule.below_cents)}" + (
            ", and she decides whether to tell you" if rule.judge else "")
    parts = [f"a deposit into {rule.account_name}" if rule.direction == "in" else f"a withdrawal from {rule.account_name}"]
    if rule.min_cents is not None:
        parts.append(f"of at least {money(rule.min_cents)}")
    if rule.payee is not None:
        parts.append(f"{'from' if rule.direction == 'in' else 'to'} a payee "
                     f"{'named' if rule.payee_match == 'exact' else 'containing'} “{rule.payee.strip()}”")
    text = " ".join(parts)
    if rule.clauses:
        text += ", when " + "; or ".join(" and ".join(predicates.say(p) for p in c) for c in rule.clauses)
    return text + (", and she decides whether to tell you" if rule.judge else "")


def to_json(rule: DepositRule) -> dict[str, object]:
    return {"account_id": rule.account_id, "account_name": rule.account_name, "min_cents": rule.min_cents,
            "payee": rule.payee, "payee_match": rule.payee_match, "direction": rule.direction,
            "clauses": [[predicates.to_json(p) for p in c] for c in rule.clauses], "judge": rule.judge,
            **({} if rule.below_cents is None else {"below_cents": rule.below_cents})}


def from_json(raw: Mapping[str, object]) -> DepositRule:
    """Raises ValueError for anything `to_json` does not make; a rule stored before `direction` existed is `in`, before
    `clauses` and `judge` had none; a rule with no `below_cents` waits on transactions."""
    account_id, name, cents, payee, how, way = (raw.get(k) for k in (
        "account_id", "account_name", "min_cents", "payee", "payee_match", "direction"))
    base = {"account_id", "account_name", "min_cents", "payee", "payee_match"}
    clauses, judge = predicates.as_list(raw.get("clauses", [])), raw.get("judge", False)
    parsed = None if clauses is None else [predicates.as_list(c) for c in clauses]
    below = raw.get("below_cents")
    if not base <= set(raw) <= base | {"direction", "clauses", "judge", "below_cents"} or type(judge) is not bool \
            or not (below is None or type(below) is int) \
            or parsed is None or any(c is None for c in parsed) \
            or way not in (None, *DIRECTIONS) \
            or not isinstance(account_id, str) or not isinstance(name, str) \
            or not (cents is None or type(cents) is int) or not (payee is None or isinstance(payee, str)) \
            or how not in PAYEE_MATCHES:
        raise ValueError("a rule is account_id, account_name, min_cents, payee, payee_match and direction")
    return DepositRule(account_id, name, cents, payee, "exact" if how == "exact" else "contains",
                       "out" if way == "out" else "in",
                       tuple(tuple(_predicate(p) for p in c or []) for c in parsed), judge, below)


def _predicate(raw: object) -> Predicate:
    got = predicates.as_map(raw)
    if got is None:
        raise ValueError("a predicate is an object")
    return predicates.from_json(got)


def money(cents: int) -> str:
    """Minor units as an amount in words' figures: 150050 is 1500.50, -500 is -5.00."""
    return f"{'-' if cents < 0 else ''}{abs(cents) // 100}.{abs(cents) % 100:02d}"
