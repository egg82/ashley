"""The Printing service (`ashley.services`): a household's printers, their AMS units, its print library and what a file
needs, as neutral records (`model`), read from whichever manager runs them. It changes three things: a print put in the
queue (`queue`, always staged), that print taken out again while it waits (`cancel`), and a file added to the library
(`upload`). What a held print shows the person is read from `file` and `printers` (`ashley.tools.printing_queue`). Callers import this module and
`model`; the adapter (for Bambuddy, `ashley.bambuddy.printing`) lives with its backend."""

from abc import abstractmethod

from ..services import Service
from .model import Cancelled, NotConnected, Need, Page, PrintFile, Printer, QueueRequest, Queueing, Uploading


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

    @abstractmethod
    async def file(self, household_id: int, file_id: str) -> PrintFile | None:
        """The library file `file_id`, None when the library has no such file. Raises PrintingFailed,
        PrintingUnavailable, NotConnected."""

    @abstractmethod
    async def queue(self, household_id: int, request: QueueRequest) -> Queueing:
        """Put a print in the queue, staged: it starts only when a person starts it in the manager. Raises
        PrintingFailed (`refused` for a key that may not queue), PrintingUnavailable, NotConnected."""

    @abstractmethod
    async def cancel(self, household_id: int, item_id: str) -> Cancelled:
        """Take the queued print `item_id` (`Queueing.item_id`) out of the queue while it still waits to be started.
        Raises PrintingFailed (`refused` for a key that may not change the queue), PrintingUnavailable, NotConnected."""

    @abstractmethod
    async def upload(self, household_id: int, name: str, data: bytes) -> Uploading:
        """Add a file to the library under `name`. Raises PrintingFailed (`refused` for a key that may not manage the
        library), PrintingUnavailable, NotConnected."""


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

    async def file(self, household_id: int, file_id: str) -> PrintFile | None:
        raise NotConnected

    async def queue(self, household_id: int, request: QueueRequest) -> Queueing:
        raise NotConnected

    async def cancel(self, household_id: int, item_id: str) -> Cancelled:
        raise NotConnected

    async def upload(self, household_id: int, name: str, data: bytes) -> Uploading:
        raise NotConnected
