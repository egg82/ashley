"""The Mailbox wired: each call goes to the adapter of the account's connection kind (`Account.kind`), and a connection of
a kind with no adapter here (Proton, where Bridge is not wired) is `refused`. A connection is readable or changeable when
its kind's adapter says so of its scopes."""

from collections.abc import Mapping

from .mailbox import Mailbox
from .model import Account, Draft, Header, Label, MailChange, MailFailed, MailQuery, Message, Page, Target


class RoutedMailbox(Mailbox):
    def __init__(self, adapters: Mapping[str, Mailbox]) -> None:
        self._adapters = dict(adapters)

    def supports(self, kind: str) -> bool:
        return kind in self._adapters

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        adapter = self._adapters.get(kind)
        return adapter is not None and adapter.can_read(kind, scopes)

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        adapter = self._adapters.get(kind)
        return adapter is not None and adapter.can_change(kind, scopes)

    async def still_syncing(self, account: Account) -> bool:
        return await self._of(account).still_syncing(account)

    async def address(self, account: Account) -> str:
        return await self._of(account).address(account)

    async def labels(self, account: Account) -> tuple[Label, ...]:
        return await self._of(account).labels(account)

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        return await self._of(account).search(account, query)

    async def read(self, account: Account, message_id: str) -> Message:
        return await self._of(account).read(account, message_id)

    async def draft(self, account: Account, draft: Draft) -> str:
        return await self._of(account).draft(account, draft)

    async def send(self, account: Account, draft: Draft) -> str:
        return await self._of(account).send(account, draft)

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        return await self._of(account).change(account, targets, change)

    def _of(self, account: Account) -> Mailbox:
        adapter = self._adapters.get(account.kind)
        if adapter is None:
            raise MailFailed("refused")
        return adapter
