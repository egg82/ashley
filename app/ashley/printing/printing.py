"""The Printing service (`ashley.services`): a household's printers, their AMS units, its print library and what a file
needs, as neutral records (`model`), read from whichever manager runs them. It only reads: queuing a print is a change
that waits for a person's OK and is not here yet. Callers import this module and `model`; the adapter (for Bambuddy,
`ashley.bambuddy.printing`) lives with its backend."""

from abc import abstractmethod

from ..services import Service
from .model import NotConnected, Need, Page, PrintFile, Printer


class Printing(Service):
    @classmethod
    def null(cls) -> "Printing":
        return NullPrinting()

    @abstractmethod
    async def connected(self, household_id: int) -> bool:
        """Whether the household has a printing manager. Raises PrintingUnavailable."""

    @abstractmethod
    async def printers(self, household_id: int, limit: int) -> Page[Printer]:
        """Up to `limit` of the household's printers with what each is doing and its AMS units. Raises PrintingFailed,
        PrintingUnavailable, NotConnected."""

    @abstractmethod
    async def files(self, household_id: int, search: str | None, limit: int) -> Page[PrintFile]:
        """Up to `limit` of the library's files, newest first, whose name holds `search` when given (any case). Raises
        PrintingFailed, PrintingUnavailable, NotConnected."""

    @abstractmethod
    async def needs(self, household_id: int, file_id: str) -> tuple[Need, ...] | None:
        """The filaments the library file `file_id` needs, None when the library has no such file. Raises PrintingFailed,
        PrintingUnavailable, NotConnected."""


class NullPrinting(Printing):
    """No household has a printing manager."""

    async def connected(self, household_id: int) -> bool:
        return False

    async def printers(self, household_id: int, limit: int) -> Page[Printer]:
        raise NotConnected

    async def files(self, household_id: int, search: str | None, limit: int) -> Page[PrintFile]:
        raise NotConnected

    async def needs(self, household_id: int, file_id: str) -> tuple[Need, ...] | None:
        raise NotConnected
