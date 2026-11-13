"""The Mailbox service (`ashley.services`): a person's mail as neutral records (`model`), reached through a connection
they made. Callers import this module and `model`; adapters live beside it (`gmail`). Reads, then the three changes:
a draft saved, a message sent, and labels, folder or read state changed on listed messages. A call logs `mail.call` with the connection, the call, the status, the count and duration_ms, never an address, a
subject, a body, a query or a token."""

from abc import abstractmethod

from ..services import Service
from .model import Account, Draft, Header, Label, MailChange, MailFailed, MailQuery, Message, Page, Target


class Mailbox(Service):
    @classmethod
    def null(cls) -> "Mailbox":
        return NullMailbox()

    def supports(self, kind: str) -> bool:
        """Whether any adapter here reads connections of `kind`, whatever scopes they were granted."""
        return True

    @abstractmethod
    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        """Whether a connection of `kind` granted `scopes` may be read."""

    async def still_syncing(self, account: Account) -> bool:
        """Whether the mailbox is still being filled in, so that a read answers `syncing`; a provider that serves its
        mail whole is never."""
        return False

    @abstractmethod
    async def address(self, account: Account) -> str:
        """The mailbox's address. Raises MailFailed."""

    @abstractmethod
    async def labels(self, account: Account) -> tuple[Label, ...]:
        """Its folders, then its labels. Raises MailFailed."""

    @abstractmethod
    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        """The headers matching `query`, newest first, at most `mail.config.MailConfig.search_max`. Raises MailFailed."""

    @abstractmethod
    async def read(self, account: Account, message_id: str) -> Message:
        """One message. Raises MailFailed (`not_found` for an id that is none of this mailbox's)."""

    @abstractmethod
    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        """Whether a connection of `kind` granted `scopes` may draft, send and change messages; one that may only read answers
        `needs_reconnect` to them."""

    @abstractmethod
    async def draft(self, account: Account, draft: Draft) -> str:
        """Save `draft` in the mailbox's drafts and give the draft's id. A caller makes it only where `can_change` says
        the connection may. Raises MailFailed (`not_found` for a `reply_to` that is none of this mailbox's, `refused` for
        a draft the provider turns away)."""

    @abstractmethod
    async def send(self, account: Account, draft: Draft) -> str:
        """Send `draft` from the mailbox once, never retried, and give the sent message's id. Raises MailFailed as
        `draft` does; `unreachable` leaves open whether it went."""

    @abstractmethod
    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        """Apply `change` to every target, or to none: each id must name a message whose sender and subject start with
        the target's (`refused` when one does not, `not_found` for an id that is none of this mailbox's, a label that is
        none of its, `refused` for a change that changes nothing). Gives how many messages changed. A caller makes it
        only where `can_change` says the connection may. Raises MailFailed."""


    async def junk(self, account: Account, targets: tuple[Target, ...]) -> bool:
        """Whether the provider itself marks every target as spam or promotions, a field it reads from the provider and
        never from the message's words. False for a target it cannot find or an adapter that reads no such mark. Raises
        MailFailed."""
        return False


class NullMailbox(Mailbox):
    def supports(self, kind: str) -> bool:
        return False

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return False

    async def address(self, account: Account) -> str:
        raise MailFailed("unreachable")

    async def labels(self, account: Account) -> tuple[Label, ...]:
        raise MailFailed("unreachable")

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        raise MailFailed("unreachable")

    async def read(self, account: Account, message_id: str) -> Message:
        raise MailFailed("unreachable")

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return False

    async def draft(self, account: Account, draft: Draft) -> str:
        raise MailFailed("unreachable")

    async def send(self, account: Account, draft: Draft) -> str:
        raise MailFailed("unreachable")

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        raise MailFailed("unreachable")
