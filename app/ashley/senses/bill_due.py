"""Bills coming due, for the deposit sense: a rule with `DepositRule.due_days` waits on a payment the household's ledger
has found repeating (`ashley.ledger.model.Recurring`) in its account, expected within that many days. A bill fires
once per bill and due date (`Deposits.due`); when the ledger moves its next date on, the next one fires. One the ledger
has only suggested counts, since the person's rule is what asks to hear of it; one it has ended, one that is income and
one without a usable id or date do not. Raises LedgerFailed, LedgerUnavailable, NotConnected."""

import logging
from datetime import date

from .. import logs, services
from ..ledger.ledger import Ledger
from ..ledger.model import Recurring
from .deposit_config import CONFIG
from .deposit_rule import Landed, names_match
from .deposits import Armed, Deposits

log = logging.getLogger("ashley.senses.deposits")

_MAX_ID = 80


async def read(household_id: int) -> list[Recurring]:
    """The household's repeating payments, up to `per_page`."""
    return list((await services.get(Ledger).recurring(household_id, CONFIG.per_page)).rows)


async def judge(household_id: int, bills: list[Armed], recurring: list[Recurring], today: date) -> int:
    """Fire each bill rule once for every bill of its account due within its days; how many fired."""
    deposits, fired = services.get(Deposits), 0
    for a in bills:
        for r in recurring:
            due = _due(r)
            if due is None or a.rule.due_days is None or r.account_id != a.rule.account_id \
                    or not 0 <= (due - today).days <= a.rule.due_days \
                    or not names_match(a.rule, tuple(n for n in (r.merchant, r.name) if n)):
                continue
            landed = Landed(r.cents, due, a.rule.account_name, r.merchant or r.name, "out", judged=a.rule.judge,
                            due_in=(due - today).days, autopay=r.autopay)
            if await deposits.due(a.id, r.id, due, landed):
                fired += 1
                logs.info(log, "deposits.billed", household=household_id, armed=a.id)
    return fired


def _due(r: Recurring) -> date | None:
    """The day `r` is expected, None for one that is not a bill to remind of."""
    if r.ended or r.kind != "expense" or r.due is None or not 1 <= len(r.id) <= _MAX_ID:
        return None
    try:
        return date.fromisoformat(r.due)
    except ValueError:
        return None
