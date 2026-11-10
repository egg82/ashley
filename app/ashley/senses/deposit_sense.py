"""The deposit sense, a singleton under the lease (`decisions.md`, "A reminder can wait on a deposit"): every `poll_s` it
reads, for each household that has an armed event reminder (`Deposits.armed`), the income transactions of its ledger
(the expense ones too when an armed rule is `out`, and only then) through the household's connection, from `lookback_days` before the day it last finished reading (`Deposits.read_through`;
the day the earliest reminder was set when it never has), and stores a once reminder for each that matches a rule
(`Deposits.fire`). The reminder's id is derived from the armed reminder and the transaction, so a retry, a second reader
or the next holder after a failover stores one. It records the day read only after every match is stored, so a poll
that fails midway is read again whole, and a deposit that lands while nobody holds the lease is found by the next
holder from the day recorded.

Logs `deposits.poll` per household with the household id, transactions read, matches, fired, whether it was cut short,
the directions read and duration_ms, `deposits.fired` per stored reminder with the armed and wake ids, and `deposits.unreadable` with the
reason when a household's ledger could not be read. Never an amount, payee or account name."""

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import logs, services
from ..ledger.model import LedgerFailed, LedgerUnavailable, NotConnected
from ..people.people import People, PeopleUnavailable
from .deposit_config import CONFIG
from ..criteria.record import DIRECTIONS, Direction
from .deposit_rule import landed, matches
from .ledger_transactions import read as read_transactions
from .deposits import Armed, Deposits, DepositsUnavailable

log = logging.getLogger("ashley.senses.deposits")

NAME = "deposits"


async def run(sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Poll every `poll_s` until cancelled."""
    failing = False
    while True:
        try:
            await poll(datetime.now(UTC))
        except DepositsUnavailable:
            if not failing:
                logs.warning(log, "deposits.unavailable")
            failing = True
        else:
            failing = False
        await sleep(CONFIG.poll_s)


async def poll(now: datetime) -> None:
    """Read every household with an armed reminder, as of `now`. Raises DepositsUnavailable."""
    by_household: dict[int, list[Armed]] = defaultdict(list)
    for armed in await services.get(Deposits).armed():
        by_household[armed.household_id].append(armed)
    for household_id, armed in by_household.items():
        await _household(household_id, armed, now)


async def _household(household_id: int, armed: list[Armed], now: datetime) -> None:
    started = time.perf_counter()
    try:
        zone = await _zone(household_id)
        since = {a.id: a.armed_at.astimezone(zone).date() for a in armed}
        deposits = services.get(Deposits)
        done = await deposits.read_through(household_id)
        start = min(since.values())
        if done is not None:
            start = max(start, done - timedelta(days=CONFIG.lookback_days))
        wider = [d for d in (a.rule.history_days(CONFIG.judged_days) for a in armed) if d is not None]
        if wider:
            start -= timedelta(days=max(wider))
        directions = _directions(armed)
        read, through = await read_transactions(household_id, start, directions)
    except (LedgerFailed, LedgerUnavailable, PeopleUnavailable, NotConnected) as e:
        logs.warning(log, "deposits.unreadable", household=household_id, reason=type(e).__name__ if not isinstance(
            e, LedgerFailed) else e.reason)
        return
    matched = fired = 0
    for a in armed:
        for d in read:
            if matches(a.rule, d, since[a.id], read):
                matched += 1
                if await deposits.fire(a.id, d.id, landed(a.rule, d, read, CONFIG.judged_days)):
                    fired += 1
                    logs.info(log, "deposits.fired", household=household_id, armed=a.id)
    today = now.astimezone(zone).date()
    await deposits.advance(household_id, today if through is None else min(today, through))
    logs.info(log, "deposits.poll", household=household_id, read=len(read), matched=matched, fired=fired, cut=through is not None,
              directions="+".join(directions), duration_ms=int((time.perf_counter() - started) * 1000))


def _directions(armed: list[Armed]) -> tuple[Direction, ...]:
    """Which ways the armed rules wait on, in `DIRECTIONS` order: the only ones worth asking the ledger for."""
    waiting = {a.rule.direction for a in armed}
    return tuple(d for d in DIRECTIONS if d in waiting)


async def _zone(household_id: int) -> ZoneInfo:
    household = await services.get(People).household(household_id)
    return ZoneInfo("UTC" if household is None else household.timezone)
