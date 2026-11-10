"""The mailboxes of a fake Proton Mail Bridge, as Bridge presents them over IMAP, with no import from `ashley`.

Modelled on what Bridge does (https://proton.me/support/protonmail-bridge-clients-apple-mail and Bridge's IMAP behaviour as
the design describes it): a person's mail is a set of messages; a folder (INBOX, Drafts, Sent, Archive, Spam, Trash) or a
label (`Labels/<name>`) holds a copy of a message under a UID of its own in that mailbox; `All Mail` holds each message
that is in none of Spam and Trash. The read state is the message's, shared by every copy; `\\Deleted` is per copy. A
resync (`Account.renumber`) gives every copy a new UID and the mailbox a new UIDVALIDITY, which is the one thing the
design says an id must survive. Unverified, hand-written: that Bridge lists `Labels/<name>` and `All Mail` exactly so, that
its special-use flags are as listed here, and that `All Mail` omits drafts never; nothing was captured from a real Bridge."""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import format_datetime

SPECIAL: dict[str, str] = {"INBOX": "", "Drafts": "\\Drafts", "Sent": "\\Sent", "Archive": "\\Archive", "Spam": "\\Junk",
                           "Trash": "\\Trash", "All Mail": "\\All"}
SYSTEM = tuple(SPECIAL)
NOT_IN_ALL = ("Spam", "Trash", "All Mail")


def crlf(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def compose(subject: str, sender: str, to: str, when: datetime, body: str = "", *, message_id: str | None = "",
            cc: str = "", html: str = "", attachments: tuple[tuple[str, str, bytes], ...] = (),
            charset: str = "utf-8", cte: str = "8bit", extra: tuple[tuple[str, str], ...] = ()) -> bytes:
    """A message as bytes with CRLF lines. `message_id` is the header's value ('' makes `<subject-hash@proton.test>`,
    None leaves the header out); `body` is the text part, `html` an alternative to it, each attachment a (name, type,
    content) one."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = sender, to, subject, format_datetime(when)
    if cc:
        msg["Cc"] = cc
    if message_id is not None:
        msg["Message-ID"] = message_id or f"<{hashlib.sha1(subject.encode()).hexdigest()[:10]}@proton.test>"
    for name, value in extra:
        msg[name] = value
    if html and not body:
        msg.set_content(html, subtype="html")
    else:
        msg.set_content(body, charset=charset, cte=cte)
        if html:
            msg.add_alternative(html, subtype="html")
    for name, media, content in attachments:
        main, _, sub = media.partition("/")
        msg.add_attachment(content, maintype=main, subtype=sub, filename=name)
    return crlf(msg.as_bytes(policy=policy.SMTP))


@dataclass
class Mail:
    """One message: its bytes, the flags every copy shows, and when it arrived."""

    raw: bytes
    flags: set[str] = field(default_factory=lambda: set[str]())
    idate: datetime = datetime(2026, 1, 1, tzinfo=UTC)

    def parsed(self) -> Message:
        return message_from_bytes(self.raw)

    @property
    def message_id(self) -> str:
        return str(self.parsed().get("Message-ID", "")).strip()


@dataclass
class Copy:
    """A message's copy in one mailbox, under a UID of that mailbox."""

    uid: int
    mail: Mail
    deleted: bool = False

    @property
    def flags(self) -> set[str]:
        return self.mail.flags | ({"\\Deleted"} if self.deleted else set[str]())


@dataclass
class Folder:
    uidvalidity: int = 1
    next_uid: int = 1
    copies: list[Copy] = field(default_factory=lambda: list[Copy]())


class Account:
    """One Bridge account's mailboxes. `commands` is every state-changing IMAP command it was sent, as (verb, folder)."""

    def __init__(self, address: str, password: str) -> None:
        self.address, self.password = address, password
        self.folders: dict[str, Folder] = {name: Folder() for name in SYSTEM}
        self.commands: list[tuple[str, str]] = []
        self.logins = 0

    def has(self, folder: str) -> bool:
        return folder in self.folders

    def make(self, folder: str) -> Folder:
        return self.folders.setdefault(folder, Folder())

    def add(self, folder: str, raw: bytes, flags: tuple[str, ...] = (), when: datetime | None = None,
            share: Mail | None = None) -> Copy:
        """Put a message in `folder`; `share` makes the copy of a message already held, so its flags are shared."""
        mail = share or Mail(crlf(raw), set(flags), when or datetime(2026, 3, 1, tzinfo=UTC))
        target = self.make(folder)
        copy = Copy(target.next_uid, mail)
        target.next_uid += 1
        target.copies.append(copy)
        self.settle()
        return copy

    def seed(self, folder: str, raw: bytes, *, labels: tuple[str, ...] = (), unread: bool = False,
             when: datetime | None = None) -> Mail:
        """A message in `folder` and in each of `Labels/<label>`, read unless `unread`."""
        first = self.add(folder, raw, () if unread else ("\\Seen",), when)
        for label in labels:
            self.add(f"Labels/{label}", raw, share=first.mail)
        return first.mail

    def settle(self) -> None:
        """`All Mail` holds one copy of each message that is in a folder or label other than Spam, Trash and itself."""
        held = {id(c.mail): c.mail for n, f in self.folders.items() if n not in NOT_IN_ALL for c in f.copies}
        allm = self.folders["All Mail"]
        allm.copies = [c for c in allm.copies if id(c.mail) in held]
        have = {id(c.mail) for c in allm.copies}
        for key, mail in held.items():
            if key not in have:
                allm.copies.append(Copy(allm.next_uid, mail))
                allm.next_uid += 1

    def expunge(self, folder: str, uids: set[int] | None = None) -> list[int]:
        """Remove the `\\Deleted` copies (only those of `uids` when given); the sequence numbers removed."""
        target = self.folders[folder]
        gone = [i + 1 for i, c in enumerate(target.copies) if c.deleted and (uids is None or c.uid in uids)]
        target.copies = [c for c in target.copies if not (c.deleted and (uids is None or c.uid in uids))]
        self.settle()
        return gone

    def renumber(self) -> None:
        """What a Bridge resync does: every copy has a new UID, in the opposite order, and the mailbox a new UIDVALIDITY."""
        for folder in self.folders.values():
            folder.uidvalidity += 7
            folder.copies.reverse()
            for n, copy in enumerate(folder.copies):
                copy.uid = 1000 + n * 3
            folder.next_uid = 1000 + len(folder.copies) * 3

    def present(self, folder: str) -> list[Mail]:
        return [c.mail for c in self.folders[folder].copies] if folder in self.folders else []

    def where(self, message_id: str) -> list[str]:
        """The mailboxes that hold the message with this Message-ID, All Mail apart."""
        return sorted(n for n, f in self.folders.items() if n != "All Mail" and any(c.mail.message_id == message_id
                                                                                      for c in f.copies))

    def unread(self, message_id: str) -> bool | None:
        for folder in self.folders.values():
            for copy in folder.copies:
                if copy.mail.message_id == message_id:
                    return "\\Seen" not in copy.mail.flags
        return None


def when(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)
