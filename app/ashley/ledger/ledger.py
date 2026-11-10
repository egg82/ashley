"""The Ledger service (`ashley.services`): a household's accounts, balances and transactions as neutral records
(`model`), read from whichever app the household keeps them in. Reads only: the interface has no call that changes
anything, so no adapter can. Callers import this module and `model`; the adapter (for Sure, `ashley.sure.ledger`) lives
with its backend."""

from abc import abstractmethod

from ..services import Service
from .model import Account, Category, Entry, NetWorth, NotConnected, Page, TransactionQuery


class Ledger(Service):
    @classmethod
    def null(cls) -> "Ledger":
        return NullLedger()

    @abstractmethod
    async def connected(self, household_id: int) -> bool:
        """Whether the household has a ledger. Raises LedgerUnavailable."""

    @abstractmethod
    async def accounts(self, household_id: int, limit: int) -> Page[Account]:
        """Up to `limit` of the household's accounts. Raises LedgerFailed, LedgerUnavailable, NotConnected."""

    @abstractmethod
    async def categories(self, household_id: int, limit: int) -> Page[Category]:
        """Up to `limit` of the household's categories. Raises LedgerFailed, LedgerUnavailable, NotConnected."""

    @abstractmethod
    async def net_worth(self, household_id: int) -> NetWorth:
        """What the household owns and owes. Raises LedgerFailed, LedgerUnavailable, NotConnected."""

    @abstractmethod
    async def transactions(self, household_id: int, query: TransactionQuery) -> Page[Entry]:
        """The transactions `query` asks for. Raises LedgerFailed, LedgerUnavailable, NotConnected."""


class NullLedger(Ledger):
    """No household has a ledger."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def accounts(self, household_id: int, limit: int) -> Page[Account]:
        raise NotConnected

    async def categories(self, household_id: int, limit: int) -> Page[Category]:
        raise NotConnected

    async def net_worth(self, household_id: int) -> NetWorth:
        raise NotConnected

    async def transactions(self, household_id: int, query: TransactionQuery) -> Page[Entry]:
        raise NotConnected
