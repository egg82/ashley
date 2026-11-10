"""The `mail_inbox` kind: a person's inbox, read as the newest `max_items` messages. A watch's target is a mailbox's
address, as `ashley.tools.mail` names one, and the person who armed it opens it as a turn that reaches them alone would
(`ConnectionResources.usable`), so a kept mailbox is read for its owner and a shared one for any member. Each message is
an item keyed by its id tracking `from`, `subject`, `unread` and `labels`. A mailbox that answers `syncing` reads as
`Later`, never as no items."""

from collections.abc import Mapping, Sequence

from .. import services
from ..connections.connections import ConnectionsUnavailable
from ..connections.resources import ConnectionResources, Usable, Use
from ..criteria.record import Change
from ..mail.mailbox import Mailbox
from ..mail.model import Account, Header, MailFailed, MailQuery, Reason
from .config import CONFIG
from .diff import Items, to_items
from .kinds import Kind
from .model import FailReason, Later, Read, ReadFailed, Watch

NAME = "mail_inbox"
INBOX = MailQuery(folder="inbox")
SORT_NOTE = ("A message arrived in the inbox you keep watch on. Sort what is in the inbox, not only the new message: "
             "search it, and tell the person only what the watch's brief says matters.")
_REASONS: dict[Reason, FailReason] = {"refused": "refused", "unreachable": "unreachable",
                                      "needs_reconnect": "not_connected", "not_found": "bad_result"}


class MailInbox(Kind):
    name = NAME
    empty_is_absent = False

    async def available(self, household_id: int, person_id: int) -> bool:
        try:
            usable = await services.get(ConnectionResources).usable(Use(household_id, person_id, True), False)
        except ConnectionsUnavailable:
            return False
        mailbox = services.get(Mailbox)
        return any(mailbox.can_read(u.connection.kind, u.connection.scopes) and u.connection.needs is None for u in usable)

    def note(self, watch: Watch, changes: Sequence[Change]) -> str:
        return SORT_NOTE

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        first = group[0]
        usable = await services.get(ConnectionResources).usable(Use(first.household_id, first.person_id, True), False)
        return {w.id: await _inbox(_mailbox(usable, w.target)) for w in group}


def _mailbox(usable: Sequence[Usable], address: str) -> Usable | None:
    return next((u for u in usable if u.resource.ref.lower() == address.lower()), None)


async def _inbox(found: Usable | None) -> Read:
    mailbox = services.get(Mailbox)
    if found is None or found.connection.needs is not None:
        return ReadFailed("not_connected")
    if not mailbox.can_read(found.connection.kind, found.connection.scopes):
        return ReadFailed("refused")
    connection = found.connection
    try:
        headers = await _newest(mailbox, Account(connection.id, connection.household_id, found.opens_for, connection.kind,
                                           found.resource.ref))
    except MailFailed as e:
        return Later() if e.reason == "syncing" else ReadFailed(_REASONS.get(e.reason, "bad_result"))
    return items_of(headers)


async def _newest(mailbox: Mailbox, account: Account) -> list[Header]:
    """The inbox's newest `max_items` headers, paged through however many answers that takes."""
    headers: list[Header] = []
    query = INBOX
    while len(headers) < CONFIG.max_items:
        page = await mailbox.search(account, query)
        headers.extend(page.items)
        if not page.cursor or not page.items:
            break
        query = MailQuery(folder=INBOX.folder, page=page.cursor)
    return headers[:CONFIG.max_items]


def items_of(headers: Sequence[Header]) -> Items:
    """Each header as an item keyed by message id; labels as one comma-joined, sorted text."""
    return to_items({h.id: {"from": h.sender, "subject": h.subject, "unread": h.unread,
                            "labels": ",".join(sorted(h.labels))} for h in headers}, CONFIG.max_value_chars)
