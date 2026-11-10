"""A mailbox's records, neutral between providers: an adapter is the only code that reads its provider's field names.
A message is named by its `id`, which the adapter gives and takes back."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

Reason = Literal["refused", "unreachable", "syncing", "needs_reconnect", "not_found"]
"""Why a call failed: `refused`, the provider turned the grant away or the call is not one it allows; `unreachable`, no
answer in time, a server error, or an answer that is not the provider's API; `syncing`, the mailbox is not yet filled
in; `needs_reconnect`, the connection's person must connect again; `not_found`, no such message."""


class MailFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True)
class Account:
    """Which connection a call is made through, and for whom: the connection visible to `person_id`. `kind` is the
    connection's kind (which adapter answers) and `address` the mailbox of it the call is for, set by whoever opens the
    connection for a mailbox; a call over a provider that has one mailbox per connection needs neither."""

    connection_id: int
    household_id: int
    person_id: int | None
    kind: str = ""
    address: str = ""


@dataclass(frozen=True)
class Label:
    """A folder (`folder` true: inbox, sent, drafts, spam, trash, named in lower case) or a label the household made."""

    name: str
    folder: bool


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    size: int


@dataclass(frozen=True)
class Header:
    """A message as a search lists it: `labels` are the household's own labels; `folder` is where it sits ('' for a
    message in none, as an archived Gmail message); `attachments` counts them."""

    id: str
    sender: str
    to: str
    subject: str
    date: datetime
    snippet: str
    labels: tuple[str, ...]
    folder: str
    unread: bool
    attachments: int


@dataclass(frozen=True)
class Message:
    """A header with its body as text (HTML turned to text), `body_cut` when the message held more than was kept."""

    header: Header
    body: str
    body_cut: bool
    attachments: tuple[Attachment, ...]


@dataclass(frozen=True)
class MailQuery:
    """What a search asks for; empty fields ask nothing. `subject` and `text` are words, `after` and `before` days,
    `folder` a folder's name as `Mailbox.labels` gives it, `unread` and `has_attachment` None for either. `page` is the
    `Page.cursor` of the answer before, '' for the first."""

    sender: str = ""
    to: str = ""
    subject: str = ""
    text: str = ""
    after: date | None = None
    before: date | None = None
    folder: str = ""
    label: str = ""
    unread: bool | None = None
    has_attachment: bool | None = None
    page: str = ""


@dataclass(frozen=True)
class Draft:
    """A message to write: plain addresses in `to` (at least one) and `cc`, a `subject`, a text `body`, and `reply_to`,
    the id of the message it answers ('' for a new one), which an adapter threads it under."""

    to: tuple[str, ...]
    subject: str
    body: str
    cc: tuple[str, ...] = ()
    reply_to: str = ""


@dataclass(frozen=True)
class Target:
    """A message a change is meant for: its `id` with the `sender` and `subject` the person was shown. An adapter
    refuses a change where the message it finds under `id` does not start with both, so an id cannot be swapped for
    another message's."""

    id: str
    sender: str
    subject: str


MOVES = ("inbox", "archive", "spam", "trash")


@dataclass(frozen=True)
class MailChange:
    """What a change does to each message: the labels (the household's, by name) to `add` and to `remove`, a `folder` to
    move it to (one of `MOVES`; '' leaves it where it is), and `unread` to mark it read (False) or unread (True); None
    leaves it. Moving to the trash is offered and deleting for good is not."""

    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    folder: str = ""
    unread: bool | None = None

    @property
    def empty(self) -> bool:
        return not (self.add or self.remove or self.folder or self.unread is not None)


@dataclass(frozen=True)
class Page[T]:
    """What one answer holds, newest first. `cut` says more matched than the answer holds; `cursor` is the `page` that
    asks for the rest, '' when there is none."""

    items: tuple[T, ...]
    cut: bool
    cursor: str = ""
