"""Pieces of the sense blind tests: a payer's past deposits in the shape Sure answers, and one poll over a household
that armed a rule."""

from dataclasses import dataclass
from datetime import date, timedelta

from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import DepositRule, Landed
from ashley.senses.wakes import Reminder
from contract.conversations_support import run
from deposit_support import NOW, DepositSure, deposit, house
from money_support import CHECKING

TODAY = NOW.date()


def payer_rows(payer: str, cents: int, *days_ago: int, ids: str = "h", classification: str = "income",
               transfer: bool = False, account_id: str = CHECKING) -> list[dict[str, object]]:
    return [deposit(f"{ids}{n}", "ACH", cents, TODAY - timedelta(days=n), merchant=payer, account_id=account_id,
                    classification=classification, transfer=transfer) for n in days_ago]


def new_row(cents: int, payer: str = "KVR", day: date = TODAY, id_: str = "new", classification: str = "income"
            ) -> dict[str, object]:
    return deposit(id_, "ACH", cents, day, merchant=payer, classification=classification)


@dataclass(frozen=True)
class Polled:
    landed: list[Landed]
    starts: list[str]


def polled(url: str, rows: list[dict[str, object]], *rules: DepositRule, polls: int = 1) -> Polled:
    out: list[Polled] = []

    async def go() -> None:
        async with house(url, DepositSure(rows=rows)) as h:
            for r in rules:
                await h.arm(r)
            for n in range(polls):
                await deposit_sense.poll(NOW + timedelta(minutes=5 * n))
            due = [w.wake.landed for w in await h.wakes.due(50)
                   if isinstance(w.wake, Reminder) and w.wake.landed is not None]
            out.append(Polled([x for x in due], sorted(q["start_date"] for q in h.sure.polls() if "start_date" in q)))

    run(go())
    return out[0]
