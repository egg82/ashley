"""The usage and remaining-balance page's data for a signed-in person: `GET /api/spend`. One log line per read with the
household id and a provider count; never an amount, key or address."""

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..channels.spend_report import Balance, Estimate, ProviderUsage, Report, SpendReport, SpendUnavailable, Spans, Totals
from .models import ErrorResponse
from .person import Person
from .spend_models import (SpendBalance, SpendEstimate, SpendProvider, SpendQuota, SpendResponse, SpendSpans,
                           SpendTask, SpendTotals, SpendWindow)

router = APIRouter()
log = logging.getLogger("ashley.api")
_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the ledger could not be read"}}


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _totals(t: Totals) -> SpendTotals:
    return SpendTotals(calls=t.calls, metered_calls=t.metered, unpriced_calls=t.metered - t.priced,
                       input_tokens=t.input_tokens, output_tokens=t.output_tokens, cache_read_tokens=t.cache_read_tokens,
                       cache_write_tokens=t.cache_write_tokens, audio_ms=t.audio_ms, characters=t.characters,
                       cost_usd=_float(t.cost_usd))


def _spans(s: Spans) -> SpendSpans:
    return SpendSpans(today=_totals(s.today), week=_totals(s.week), month=_totals(s.month))


def _balance(b: Balance) -> SpendBalance:
    q = b.quota
    quota = None if q is None else SpendQuota(unit=q.unit, used=q.used, limit=q.limit,
                                              remaining=max(q.limit - q.used, 0), resets_at=q.resets_at)
    return SpendBalance(state=b.state, quota=quota, read_at=b.read_at, why=b.why, docs_url=b.source)


def _estimate(e: Estimate | None) -> SpendEstimate | None:
    return None if e is None else SpendEstimate(
        budget_usd=float(e.budget_usd), spent_usd=float(e.spent_usd), remaining_usd=float(e.remaining_usd),
        unpriced_calls=e.unpriced_calls)


def _provider(p: ProviderUsage) -> SpendProvider:
    return SpendProvider(provider=p.provider, label=p.label, kind=p.kind, usage=_spans(p.spans),
                         tasks=[SpendTask(task=t.task, usage=_spans(t.spans)) for t in p.tasks],
                         balance=_balance(p.balance), estimate=_estimate(p.estimate))


def _wire(report: Report) -> SpendResponse:
    return SpendResponse(zone=report.zone, as_of=report.as_of,
                         windows=[SpendWindow(name=w.name, starts_at=w.starts) for w in report.spans],
                         providers=[_provider(p) for p in report.providers])


@router.get("/api/spend", response_model=SpendResponse, responses=_RESPONSES)
async def read_spend(signed_in: Person) -> SpendResponse | JSONResponse:
    """200 `SpendResponse`; 401 `unauthorized`; 503 `unavailable`."""
    household = signed_in.person.household_id
    try:
        report = await services.get(SpendReport).report(household)
    except SpendUnavailable:
        logs.warning(log, "spend.unavailable", household=household)
        return JSONResponse(status_code=503, content=ErrorResponse(
            code="unavailable", detail="usage is unavailable right now; try again shortly").model_dump())
    return _wire(report)
