"""Proton as a Mailbox, over IMAP and SMTP to Proton Mail Bridge (`decisions.md`, "Bridge runs as a leased singleton whose
vault outlives its pod"). A call signs in as the mailbox's address with the Bridge password its connection holds, at the
Bridge Service address of each site in turn, under the certificate Bridge reported (`proton_endpoint`). The wire is
`imap_wire`, ids and ordering `imap_reads`, changes `imap_writes`, sending `smtp_send`; this module decides whether a call
may be made and how it is logged.

Until Bridge has finished syncing the account in its current epoch it serves the mailbox empty, so every call answers
`syncing`, never a result that reads as no mail; an account Bridge signed out answers `needs_reconnect`. A Proton
connection carries no OAuth scopes, and the router sends only a Proton connection here. A call logs
`mail.call` as Gmail's does, never an address, subject, query or password."""

import asyncio
from collections.abc import Awaitable, Callable

from .. import services
from ..connections.connections import Connections, ConnectionsUnavailable
from . import calls, imap_reads, imap_writes, proton_pod, smtp_send
from .config import MailConfig
from .imap_wire import Imap
from .mailbox import Mailbox
from .model import Account, Draft, Header, Label, MailChange, MailFailed, MailQuery, Message, Page, Target
from .proton_bridge import Account as BridgeAccount, BridgeUnavailable, ProtonBridge
from .proton_endpoint import Login


class ImapMailbox(Mailbox):
    def __init__(self, hosts: tuple[str, ...], config: MailConfig, imap_port: int = proton_pod.IMAP_PORT,
                 smtp_port: int = proton_pod.SMTP_PORT) -> None:
        """`hosts` are the Bridge Service addresses (host names), this site's first, and the ports are the pod's."""
        self._hosts = hosts
        self._config = config
        self._ports = (imap_port, smtp_port)

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return True

    async def still_syncing(self, account: Account) -> bool:
        try:
            held = await _held(account)
        except MailFailed:
            return False
        return held.syncing

    async def address(self, account: Account) -> str:
        async def work(login: Login) -> tuple[str, int]:
            return login.address, 1
        return await self._timed("address", account, work)

    async def labels(self, account: Account) -> tuple[Label, ...]:
        def work(session: Imap) -> tuple[tuple[Label, ...], int]:
            found = imap_reads.labels(session, self._config)
            return found, len(found)
        return await self._imap("labels", account, work)

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        def work(session: Imap) -> tuple[Page[Header], int]:
            page = imap_reads.search(session, query, self._config)
            return page, len(page.items)
        return await self._imap("search", account, work)

    async def read(self, account: Account, message_id: str) -> Message:
        def work(session: Imap) -> tuple[Message, int]:
            return imap_reads.read(session, message_id, self._config), 1
        return await self._imap("read", account, work)

    async def draft(self, account: Account, draft: Draft) -> str:
        def work(session: Imap) -> tuple[str, int]:
            return imap_writes.draft(session, account.address, draft, self._config), 1
        return await self._imap("draft", account, work)

    async def send(self, account: Account, draft: Draft) -> str:
        async def work(login: Login) -> tuple[str, int]:
            return await asyncio.to_thread(self._send, login, draft), 1
        return await self._timed("send", account, work)

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        def work(session: Imap) -> tuple[int, int]:
            done = imap_writes.change(session, targets, change, self._config)
            return done, done
        return await self._imap("change", account, work)

    async def junk(self, account: Account, targets: tuple[Target, ...]) -> bool:
        def work(session: Imap) -> tuple[bool, int]:
            return imap_writes.in_spam(session, targets, self._config), len(targets)
        return await self._imap("junk", account, work)

    def _send(self, login: Login, draft: Draft) -> str:
        """Build the message, looking up the one it answers over IMAP when it answers one, and hand it to SMTP."""
        session = Imap.open(login, self._config.timeout_s) if draft.reply_to else None
        try:
            built, ident = imap_writes.outgoing(session, login.address, draft, self._config)
        finally:
            if session is not None:
                session.close()
        smtp_send.send(login, (*draft.to, *draft.cc), built.as_bytes(), self._config.timeout_s)
        return ident

    async def _imap[T](self, call: str, account: Account, work: Callable[[Imap], tuple[T, int]]) -> T:
        def run(login: Login) -> tuple[T, int]:
            session = Imap.open(login, self._config.timeout_s)
            try:
                return work(session)
            finally:
                session.close()

        async def threaded(login: Login) -> tuple[T, int]:
            return await asyncio.to_thread(run, login)

        return await self._timed(call, account, threaded)

    async def _timed[T](self, call: str, account: Account, work: Callable[[Login], Awaitable[tuple[T, int]]]) -> T:
        async def run() -> tuple[T, int]:
            return await work(await self._login(account))

        return await calls.logged(call, account, run)

    async def _login(self, account: Account) -> Login:
        held = await _held(account)
        if held.syncing:
            raise MailFailed("syncing")
        if account.address.lower() not in {a.lower() for a in held.addresses}:
            raise MailFailed("not_found")
        try:
            fingerprint = (await services.get(ProtonBridge).holder()).certificate_sha256
            opened = await services.get(Connections).opened(account.connection_id, account.household_id, account.person_id)
        except (BridgeUnavailable, ConnectionsUnavailable) as e:
            raise MailFailed("unreachable") from e
        if opened is None:
            raise MailFailed("refused")
        if fingerprint is None:
            raise MailFailed("unreachable")
        return Login(self._hosts, *self._ports, fingerprint, account.address, opened.secret)


async def _held(account: Account) -> BridgeAccount:
    """The Bridge account the connection is. Raises MailFailed: `needs_reconnect` for one Bridge signed out or locked,
    `refused` for a connection Bridge holds none for, `unreachable` when the record cannot be read."""
    try:
        accounts = await services.get(ProtonBridge).accounts()
    except BridgeUnavailable as e:
        raise MailFailed("unreachable") from e
    found = next((a for a in accounts if a.connection_id == account.connection_id), None)
    if found is None:
        raise MailFailed("refused")
    if found.state != "connected":
        raise MailFailed("needs_reconnect")
    return found
