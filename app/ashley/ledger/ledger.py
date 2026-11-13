"""The Ledger service (`ashley.services`): a household's accounts, balances and transactions as neutral records
(`model`), read from whichever app the household keeps them in. The one change it makes is a transaction's category
(`categorise`); its callers offer it only through a gated change tool (`ashley.tools.money`). Callers import this module
and `model`; the adapter (for Sure, `ashley.sure.ledger`) lives with its backend."""

from abc import abstractmethod
from collections.abc import Mapping, Sequence

from ..services import Service
from .model import Account, Categorised, Category, Entry, NetWorth, NotConnected, Page, TransactionQuery


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

    @abstractmethod
    async def categorise(self, household_id: int, category_id: str,
                         transaction_ids: Sequence[str]) -> Mapping[str, Categorised]:
        """Set each of `transaction_ids` to the household's category `category_id`, in order; what became of each, by
        id. Nothing is changed when the category is not the household's. A failure part way leaves the ones before it
        changed; setting a category again is harmless. Raises UnknownCategory, LedgerFailed, LedgerUnavailable,
        NotConnected."""


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

    async def categorise(self, household_id: int, category_id: str,
                         transaction_ids: Sequence[str]) -> Mapping[str, Categorised]:
        raise NotConnected
