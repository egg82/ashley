"""Which Discord messages have been claimed: a message is answered only by the process whose claim lands, so two
Gateway sessions (a failover's overlap, a catch-up repeating a live message) never both reply. A claim is settled once
the turn loop has the message in hand, so a claim its session died holding is handed in again by the next (the turn
loop makes that the same turn, `Inbound.source`). Message and channel ids are logged; nothing else is stored."""

from abc import ABC, abstractmethod
from datetime import datetime


class SeenUnavailable(Exception):
    """The database could not be written or read (a read-only primary included). Transient."""


class Seen(ABC):
    @abstractmethod
    async def claim(self, message_id: int, channel_id: int) -> bool:
        """True for exactly one caller per message id, ever (until pruned); False when already claimed. Raises
        SeenUnavailable when the database cannot be written (a read-only primary included)."""

    @abstractmethod
    async def last(self, since: datetime) -> dict[int, int]:
        """Per channel id, the greatest claimed message id among claims made at or after `since`. Raises
        SeenUnavailable."""

    @abstractmethod
    async def prune(self, before: datetime) -> int:
        """Delete claims made before `before`; how many. Raises SeenUnavailable."""

    @abstractmethod
    async def settle(self, message_id: int) -> None:
        """Mark the claim on `message_id` settled: the turn loop answered it, saved its work or failed it, so no session
        hands it in again. Nothing for a message never claimed, or settled already. Raises SeenUnavailable."""

    @abstractmethod
    async def unsettled(self, since: datetime) -> dict[int, int]:
        """Message id to channel id of each claim made at or after `since` that was never settled. Raises
        SeenUnavailable."""
