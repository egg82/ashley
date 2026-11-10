"""Pieces of the withdrawal-sense blind tests: rows in the shape Sure answers (an income row's `signed_amount_cents` is
positive, an expense's negative), rules in either direction, and a household that polls them on a real database."""

from dataclasses import dataclass
from datetime import date, timedelta

from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import DepositRule, Direction, PayeeMatch
from ashley.senses.wakes import Reminder
from contract.conversations_support import run
from deposit_support import NOW, DepositSure, deposit, house
from money_support import CHECKING

DAY = date(2026, 11, 3)
SECRET_PAYEE = "ZqSentinelPayee"
SECRET_ACCOUNT = "ZqSentinelAccount"


def row(id_: str, cents: int = 60_000, direction: Direction = "out", payee: str | None = "Statewide Mutual", day: date = DAY,
        account_id: str = CHECKING, name: str = "ACH debit", transfer: bool = False, excluded: bool = False,
        split_parent: bool = False) -> dict[str, object]:
    made = deposit(id_, name, cents, day, merchant=payee, account_id=account_id,
                   classification="income" if direction == "in" else "expense", transfer=transfer)
    made.update(excluded=excluded, split_parent=split_parent)
    return made


def rule_for(direction: Direction, min_cents: int | None = 50_000, payee: str | None = None, match: PayeeMatch = "contains",
             account_name: str = "Checking") -> DepositRule:
    return DepositRule(CHECKING, account_name, min_cents, payee, match, direction)


@dataclass(frozen=True)
class Fired:
    """What a run of polls stored: one entry per reminder due, as the transaction it landed on."""

    cents: list[int]
    directions: list[Direction]
    types_read: list[str]


async def _polled(url: str, rows: list[dict[str, object]], *rules: DepositRule, polls: int = 1) -> Fired:
    async with house(url, DepositSure(rows=rows)) as h:
        for armed in rules:
            await h.arm(armed)
        for hour in range(polls):
            await deposit_sense.poll(NOW + timedelta(hours=hour))
        landed = [w.wake.landed for w in await h.wakes.due(50)
                  if isinstance(w.wake, Reminder) and w.wake.landed is not None]
        return Fired([x.cents for x in landed], [x.direction for x in landed],
                     sorted({q["type"] for q in h.sure.polls() if "type" in q}))


def polled(url: str, rows: list[dict[str, object]], *rules: DepositRule, polls: int = 1) -> Fired:
    out: list[Fired] = []

    async def go() -> None:
        out.append(await _polled(url, rows, *rules, polls=polls))

    run(go())
    return out[0]
