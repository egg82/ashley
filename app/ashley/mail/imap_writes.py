"""The changes of the IMAP adapter over one `Imap` session. A draft is appended to `Drafts` with the `\\Draft` flag;
sending is `smtp_send` (Bridge keeps the sent message in `Sent` itself); a change is made as Bridge reads IMAP: copying a
message into `Labels/<name>` gives it the label, deleting it from that folder takes the label off, copying it to a folder
and deleting it from the one it was in moves it, and `\\Seen` is read state.

A change reads every target first and changes nothing unless each is a message whose sender and subject begin with what
the person was shown. IMAP has no batch, so a failure part way through leaves the messages before it changed."""

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from . import compose, imap_message
from .config import MailConfig
from .imap_find import HEADERS, SYSTEM, Found, labelled
from .imap_reads import located
from .imap_wire import Imap
from .model import Draft, MailChange, MailFailed, Target
from .targets import shown


def outgoing(session: Imap | None, address: str, draft: Draft, config: MailConfig) -> tuple[EmailMessage, str]:
    """`draft` as the message the mailbox writes, from `address`, threaded under the one it answers (found through
    `session`, which a draft that answers none does not need), and its id. Raises MailFailed."""
    replied, references = "", ""
    if draft.reply_to:
        assert session is not None
        found = located(session, session.folders(), draft.reply_to, config)
        replied, references = str(found.message.get("Message-ID", "")).strip(), str(found.message.get("References", ""))
    built = compose.message(draft, replied, references)
    domain = address.rpartition("@")[2] or None
    try:
        built["From"] = address
        built["Date"] = format_datetime(datetime.now(UTC))
        built["Message-ID"] = make_msgid(domain=domain)
    except (ValueError, TypeError) as e:
        raise MailFailed("refused") from e
    return built, imap_message.ident(built, config.message_id_chars)


def draft(session: Imap, address: str, written: Draft, config: MailConfig) -> str:
    """Save `written` in `Drafts` and give its id."""
    built, ident = outgoing(session, address, written, config)
    session.append(SYSTEM["drafts"], "(\\Draft)", built.as_bytes())
    return ident


def change(session: Imap, targets: tuple[Target, ...], what: MailChange, config: MailConfig) -> int:
    names = session.folders()
    wanted = list({t.id: t for t in targets}.values())
    if not wanted or what.empty:
        raise MailFailed("refused")
    add, remove = _folders(what.add, names), _folders(what.remove, names)
    if set(add) & set(remove) or (what.folder and what.folder not in SYSTEM) or (what.folder and SYSTEM[what.folder] not in names):
        raise MailFailed("refused")
    found = [located(session, names, t.id, config) for t in wanted]
    if not all(_is_shown(f, t) for f, t in zip(found, wanted, strict=True)):
        raise MailFailed("refused")
    for message in found:
        _apply(session, message, what, add, remove, config)
    return len(wanted)


def _folders(named: tuple[str, ...], names: tuple[str, ...]) -> list[str]:
    """Bridge's folder for each label name, once each. Raises MailFailed `not_found` for one that is none of the
    mailbox's labels."""
    known = labelled(names)
    found = [known.get(n.strip().lower()) for n in named]
    if None in found:
        raise MailFailed("not_found")
    return list(dict.fromkeys(f for f in found if f is not None))


def _is_shown(found: Found, target: Target) -> bool:
    return shown(str(found.message.get("From", "")), target.sender) and shown(str(found.message.get("Subject", "")),
                                                                              target.subject)


def _apply(session: Imap, message: Found, what: MailChange, add: list[str], remove: list[str], config: MailConfig) -> None:
    if what.unread is not None:
        session.flag(message.imap, message.uid, "\\Seen", not what.unread)
    for folder in add:
        session.copy(message.imap, message.uid, folder)
    for folder in remove:
        ident = imap_message.ident(message.message, config.message_id_chars)
        uids = session.header_search(folder, "Message-ID", ident)
        for item in session.fetch(folder, uids, HEADERS):
            if imap_message.ident(imap_message.parse(item.body), config.message_id_chars) == ident:
                session.delete(folder, item.uid)
    target = SYSTEM.get(what.folder, "")
    if target and target != message.imap:
        session.copy(message.imap, message.uid, target)
        session.delete(message.imap, message.uid)

