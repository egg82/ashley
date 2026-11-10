"""Finding a message by its id, and where Bridge keeps folders. A mailbox's folders are `INBOX`, `Archive`, `Sent`,
`Drafts`, `Trash` and `Spam`; a label is a folder `Labels/<name>` holding a copy of each message that has it. A message is
looked for in the six folders, never in a label or in `All Mail`, so what is found is where it sits."""

from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

from . import imap_message
from .imap_terms import Criteria
from .imap_wire import Fetched, Imap

SYSTEM = {"inbox": "INBOX", "archive": "Archive", "sent": "Sent", "drafts": "Drafts", "spam": "Spam", "trash": "Trash"}
"""The port's folder names to Bridge's."""
SEARCHED = ("inbox", "archive", "sent", "drafts")
"""What a search with no folder covers, as Gmail's leaves out the spam and the trash."""
LOCATED = ("inbox", "archive", "sent", "drafts", "trash", "spam")
LABELS = "Labels/"
SCAN_MAX = 200
"""The newest messages of a folder looked through for one with no `Message-ID` (and the most one search reads, a
`has_attachment` filter included), since IMAP can search neither by the id this gives such a message nor by an attachment."""
HEADERS = "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE FROM TO SUBJECT REFERENCES)]"


@dataclass(frozen=True)
class Found:
    """A message as located: the port's `folder` name, Bridge's name for it (`imap`), its `uid` there, its `flags`, the
    time it was `received` and its parsed headers."""

    folder: str
    imap: str
    uid: int
    flags: frozenset[str]
    received: datetime | None
    message: EmailMessage


def label_folder(name: str) -> str:
    return LABELS + name


def labelled(names: tuple[str, ...]) -> dict[str, str]:
    """The household's labels in the folder list: lower-case name to Bridge's folder."""
    return {n[len(LABELS):].lower(): n for n in names if n.startswith(LABELS) and len(n) > len(LABELS)}


def locate(session: Imap, names: tuple[str, ...], ident: str, longest: int) -> Found | None:
    """The message `ident` names, in the first of `LOCATED` that holds it. Raises MailFailed."""
    for folder in LOCATED:
        imap = SYSTEM[folder]
        if imap not in names:
            continue
        for item in _candidates(session, imap, ident):
            message = imap_message.parse(item.body)
            if imap_message.ident(message, longest) == ident:
                return Found(folder, imap, item.uid, item.flags, item.received, message)
    return None


def _candidates(session: Imap, imap: str, ident: str) -> list[Fetched]:
    if imap_message.NOMID.fullmatch(ident):
        uids = session.search(imap, Criteria())[-SCAN_MAX:]
    else:
        uids = session.header_search(imap, "Message-ID", ident)
    return session.fetch(imap, uids, HEADERS)
