"""The Stock service (`ashley.services`): the spools a household has, as neutral records (`model`), read from whichever
app keeps them. When the household connects more than one app that supplies stock, the first of them opens
(`ashley.connections.ports.opened`, in the registration order of `ashley.wiring.CONNECTION_KINDS`). Callers import this
module and `model`; the adapter (for Bambuddy, `ashley.bambuddy.stock`) lives with its backend."""

from abc import abstractmethod

from ..services import Service
from .model import NotConnected, Page, Spool


class Stock(Service):
    @classmethod
    def null(cls) -> "Stock":
        return NullStock()

    @abstractmethod
    async def connected(self, household_id: int) -> bool:
        """Whether the household has a filament stock. Raises StockUnavailable."""

    @abstractmethod
    async def spools(self, household_id: int, limit: int) -> Page[Spool]:
        """Up to `limit` of the household's spools in stock (an archived one is not), most filament left first.
        Raises StockFailed, StockUnavailable, NotConnected."""


class NullStock(Stock):
    """No household has a stock."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def spools(self, household_id: int, limit: int) -> Page[Spool]:
        raise NotConnected
