"""The spend ledger: one row per model call, by task, provider and model, kept (it is a ledger, not a log) so spend
against the monthly API credit can be read back. Only `RoutedInference` writes it."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .model import TaskName, Usage
from .provider import Failure

Outcome = Literal["ok", "refused"] | Failure


@dataclass(frozen=True)
class Call:
    """One model call as recorded. `usage` is None when the provider reported none; `cost_usd` is None when the model
    has no price (`prices.cost_usd`) or `usage` is None, and is never a guess. `conversation_id` is the conversation the call served, None when it served none."""

    task: TaskName
    provider: str
    model: str
    outcome: Outcome
    usage: Usage | None
    cost_usd: Decimal | None
    duration_ms: int
    conversation_id: int | None = None


class SpendLedger(ABC):
    @abstractmethod
    async def record(self, call: Call) -> None:
        """Store `call`, stamped with the database's clock. Raises on any failure to store it; the caller decides
        what a lost row costs."""
