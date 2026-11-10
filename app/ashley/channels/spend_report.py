"""The SpendReport service (`ashley.services`): what each provider has been used for and cost, and what it says is left,
for a household's page. Callers import only this module; `spend_view` implements it over the spend ledger
(`ashley.inference.spend_tally`), the provider balances (`ashley.inference.balance`) and the catalog
(`ashley.inference.spend_catalog`).

The ledger is the app's, not a household's, so every household sees the same usage; the household's time zone sets where
a day begins. Cost is the ledger's own: published list prices (`prices.json`) times the usage a provider reported."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from ..inference.balance import Quota
from ..inference.spend_windows import Window
from ..services import Service


class SpendUnavailable(Exception):
    """The ledger or the household could not be read. Transient."""


@dataclass(frozen=True)
class Totals:
    """Usage over one span. `metered` of the `calls` reported usage and `priced` of those had a cost; a sum is None when
    no call it covers reported one, so a missing value is never a 0. `metered` less `priced` is the calls whose usage had
    no price, which `cost_usd` leaves out."""

    calls: int
    metered: int
    priced: int
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    audio_ms: int | None
    characters: int | None
    cost_usd: Decimal | None


@dataclass(frozen=True)
class Spans:
    """The same usage over the three spans."""

    today: Totals
    week: Totals
    month: Totals


@dataclass(frozen=True)
class TaskUsage:
    task: str
    spans: Spans


@dataclass(frozen=True)
class Balance:
    """`read`: the provider's own `quota`, read at `read_at`. `failed`: a read was tried at `read_at` and gave nothing.
    `unknown`: no read is possible or wired, and `why` says which. `free`: a local model, with nothing to run out of."""

    state: Literal["read", "failed", "unknown", "free"]
    quota: Quota | None
    read_at: datetime | None
    why: str | None
    source: str | None


@dataclass(frozen=True)
class Estimate:
    """A monthly budget the household set, less this month's ledger spend. `unpriced_calls` is this month's calls with no
    price, which the spend leaves out, so the remainder is an upper bound whenever it is above 0."""

    budget_usd: Decimal
    spent_usd: Decimal
    remaining_usd: Decimal
    unpriced_calls: int


@dataclass(frozen=True)
class ProviderUsage:
    provider: str
    label: str
    kind: Literal["paid", "local", "unlisted"]
    spans: Spans
    tasks: tuple[TaskUsage, ...]
    balance: Balance
    estimate: Estimate | None


@dataclass(frozen=True)
class Report:
    """`spans` are the windows the totals cover, as of `as_of`, in `zone` (an IANA name)."""

    zone: str
    as_of: datetime
    spans: tuple[Window, Window, Window]
    providers: tuple[ProviderUsage, ...]


class SpendReport(Service):
    @classmethod
    def null(cls) -> "SpendReport":
        return NullSpendReport()

    @abstractmethod
    async def report(self, household_id: int) -> Report:
        """Every paid provider, and any other with calls in the spans, in catalog order then by name. Raises
        SpendUnavailable."""


class NullSpendReport(SpendReport):
    """Reports nothing: raises SpendUnavailable, so a missing registration is a 503."""

    async def report(self, household_id: int) -> Report:
        raise SpendUnavailable("SpendReport is not wired")
