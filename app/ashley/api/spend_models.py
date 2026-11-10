"""The wire models of `GET /api/spend` (`api-contract-first`): provider usage over three spans and what each provider
says is left.

Every count and sum covers only the calls that reported it: a field is null, never 0, when no call in the span
reported a value, and `metered_calls` less `unpriced_calls` is how many calls `cost_usd` rests on."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SpendTotals(BaseModel):
    """Usage over one span. `calls` counts every call, including failed ones; `metered_calls` those that reported
    usage; `unpriced_calls` those whose usage has no price, which `cost_usd` leaves out. `cost_usd` is the ledger's:
    published list prices times reported usage, null when no call had a price. Speech is billed by `characters` and
    `audio_ms`, and its tokens are 0."""

    calls: int
    metered_calls: int
    unpriced_calls: int
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    audio_ms: int | None
    characters: int | None
    cost_usd: float | None


class SpendSpans(BaseModel):
    """The same usage over the three spans."""

    today: SpendTotals
    week: SpendTotals
    month: SpendTotals


class SpendTask(BaseModel):
    """One task's share of a provider's usage."""

    task: str
    usage: SpendSpans


class SpendQuota(BaseModel):
    """What the provider itself reports of an account's allowance in the current period, in its own `unit`; not money."""

    unit: Literal["characters"]
    used: int
    limit: int
    remaining: int
    resets_at: datetime | None


class SpendBalance(BaseModel):
    """`read`: `quota` as of `read_at`. `failed`: a read was tried at `read_at` and gave nothing. `unknown`: the provider
    offers no read, or none is set up here, and `why` says which. `free`: a local model, with nothing to run out of.
    `docs_url` is the documentation page for the provider's billing, when there is one."""

    state: Literal["read", "failed", "unknown", "free"]
    quota: SpendQuota | None
    read_at: datetime | None
    why: str | None
    docs_url: str | None


class SpendEstimate(BaseModel):
    """The household's monthly budget less this month's ledger spend: an estimate, not the provider's figure. While
    `unpriced_calls` is above 0 the remainder is an upper bound."""

    budget_usd: float
    spent_usd: float
    remaining_usd: float
    unpriced_calls: int


class SpendProvider(BaseModel):
    """`kind`: `paid` and `local` as the catalog says, `unlisted` for a provider the ledger holds that the catalog does
    not name."""

    provider: str
    label: str
    kind: Literal["paid", "local", "unlisted"]
    usage: SpendSpans
    tasks: list[SpendTask]
    balance: SpendBalance
    estimate: SpendEstimate | None


class SpendWindow(BaseModel):
    """A span's start, an instant: local midnight in the report's zone."""

    name: Literal["today", "week", "month"]
    starts_at: datetime


class SpendResponse(BaseModel):
    """Usage as of `as_of`, in the household's time zone `zone` (an IANA name). Providers are the paid ones first, in
    catalog order, then any other with calls in the spans, by name."""

    zone: str
    as_of: datetime
    windows: list[SpendWindow]
    providers: list[SpendProvider]
