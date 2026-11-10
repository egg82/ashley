"""`SpendView`: the SpendReport over the ledger, the household's time zone, the provider balances and the catalog."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from itertools import groupby
from zoneinfo import ZoneInfo

import psycopg

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from ..inference.balance import ProviderBalances, Reading
from ..inference.spend_catalog import Catalog, ProviderInfo
from ..inference.spend_tally import Tally, tally
from ..inference.spend_windows import windows
from ..people.people import People, PeopleUnavailable
from .spend_report import Balance, Estimate, ProviderUsage, Report, SpendReport, SpendUnavailable, TaskUsage, Totals
from .spend_totals import spans_of

log = logging.getLogger("ashley.channels")
_NOT_SET_UP = "its key is not set here"
_UNLISTED = "no way to read a balance is known for this provider"


def _balance(info: ProviderInfo | None, reading: Reading | None) -> Balance:
    source = None if info is None else info.source
    if info is not None and info.kind == "local":
        return Balance("free", None, None, None, None)
    if reading is None:
        why = _UNLISTED if info is None else info.why_unknown or _NOT_SET_UP
        return Balance("unknown", None, None, why, source)
    return Balance("read" if reading.quota is not None else "failed", reading.quota, reading.read_at, None, source)


def _estimate(budget: float | None, month: Totals) -> Estimate | None:
    if budget is None:
        return None
    spent = month.cost_usd or Decimal(0)
    return Estimate(Decimal(repr(budget)), spent, Decimal(repr(budget)) - spent, month.metered - month.priced)


class SpendView(SpendReport):
    def __init__(self, database: Database, people: Callable[[], People], balances: Callable[[], ProviderBalances],
                 catalog: Catalog, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._database = database
        self._people = people
        self._balances = balances
        self._catalog = catalog
        self._now = now

    async def report(self, household_id: int) -> Report:
        try:
            household = await self._people().household(household_id)
            zone = ZoneInfo("UTC" if household is None else household.timezone)
            as_of = self._now()
            spans = windows(as_of, zone)
            tallies = await tally(self._database, spans)
        except (DatabaseUnavailable, psycopg.OperationalError, PeopleUnavailable) as e:
            raise SpendUnavailable(type(e).__name__) from e
        by_provider = {name: list(rows) for name, rows in groupby(tallies, key=lambda t: t.provider)}
        paid = [name for name, info in self._catalog.providers.items() if info.kind == "paid"]
        names = paid + sorted(set(by_provider) - set(paid))
        readings = await asyncio.gather(*(self._reading(name) for name in names))
        shown = tuple(self._usage(name, by_provider.get(name, []), reading) for name, reading in zip(names, readings))
        logs.info(log, "spend.report", household=household_id, providers=len(shown), rows=len(tallies))
        return Report(zone.key, as_of, spans, shown)

    async def _reading(self, provider: str) -> Reading | None:
        info = self._catalog.providers.get(provider)
        return None if info is not None and info.kind == "local" else await self._balances().reading(provider)

    def _usage(self, provider: str, rows: list[Tally], reading: Reading | None) -> ProviderUsage:
        info = self._catalog.providers.get(provider)
        spans = spans_of(rows)
        tasks = tuple(TaskUsage(task, spans_of(task_rows)) for task, task_rows in
                      groupby(sorted(rows, key=lambda t: t.task), key=lambda t: t.task))
        return ProviderUsage(provider, provider if info is None else info.label, "unlisted" if info is None else info.kind,
                             spans, tasks, _balance(info, reading),
                             _estimate(self._catalog.monthly_usd.get(provider), spans.month))
