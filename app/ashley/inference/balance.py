"""The ProviderBalances service (`ashley.services`): what a provider says is left of what was bought, where it has a way
to say so. A provider whose way is not wired, or has none, answers None: unknown, never an amount.

Each way to read is a `BalanceSource`, one per provider name (the ledger's, `Provider.name`). A read is cached briefly,
a failed one too, so a page opened by several people asks the provider once."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..services import Service

Outcome = Literal["ok", "refused", "http_error", "unreachable", "malformed"]


@dataclass(frozen=True)
class Quota:
    """A provider's own count of what an account may use: `used` of `limit` `unit`s in the current period, which ends
    at `resets_at` (None when the provider does not say)."""

    unit: Literal["characters"]
    used: int
    limit: int
    resets_at: datetime | None


class BalanceFailed(Exception):
    """A read that produced no quota. `outcome` says why: `refused` (the key was not accepted), `http_error` (any other
    status), `unreachable` (no answer in time), `malformed` (an answer without the quota). The message names no key,
    URL or amount."""

    def __init__(self, outcome: Outcome) -> None:
        super().__init__(outcome)
        self.outcome: Outcome = outcome


class BalanceSource(ABC):
    @abstractmethod
    async def read(self) -> Quota:
        """The provider's quota now. Raises `BalanceFailed`."""


@dataclass(frozen=True)
class Reading:
    """One read, taken at `read_at`: `quota` is None when it failed."""

    read_at: datetime
    quota: Quota | None


class ProviderBalances(Service):
    @classmethod
    def null(cls) -> "ProviderBalances":
        return NullBalances()

    @abstractmethod
    async def reading(self, provider: str) -> Reading | None:
        """The latest read of `provider`'s balance, at most a minute old; None when no way to read one is wired for it.
        Never raises: a failed read is a `Reading` with no quota."""


class NullBalances(ProviderBalances):
    """Reads nothing: every provider is unknown."""

    async def reading(self, provider: str) -> Reading | None:
        return None
