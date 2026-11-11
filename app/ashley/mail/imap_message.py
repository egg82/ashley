"""A message as Bridge serves it (RFC 2822 text) as the port's records. A message is named by its `Message-ID` header
without the angle brackets, cut to `message_id_chars`, so an id survives a resync, which gives every message a new UID;
a message with none is named `nomid-` and a hash of its date, sender and subject. Headers are decoded by `email`'s own
policy, the body as `ashley.mail.body` does for Gmail's: the plain parts when there are any, else the HTML parts as text."""

import hashlib
import re
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage, Message as RawMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from ..text import without_nul
from . import body
from .model import Attachment, Header, Message

NOMID = re.compile(r"nomid-[0-9a-f]{32}")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")


def parse(raw: bytes) -> EmailMessage:
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    assert isinstance(parsed, EmailMessage)
    return parsed


def valid(ident: str, longest: int) -> bool:
    """Whether `ident` can be an id this module gave: not empty, within `longest`, no control character or space."""
    return bool(ident) and len(ident) <= longest and _CONTROL.search(ident) is None


def ident(message: RawMessage, longest: int) -> str:
    """The id of a parsed message (its headers are enough)."""
    given = _CONTROL.sub("", str(message.get("Message-ID", ""))).strip("<>")
    if given:
        return given[:longest]
    seen = "|".join(str(message.get(h, "")) for h in ("Date", "From", "Subject"))
    return "nomid-" + hashlib.sha256(seen.encode()).hexdigest()[:32]


def header(message: EmailMessage, longest: int, snippet_chars: int, text: str, attachments: int, labels: tuple[str, ...],
           folder: str, unread: bool, received: datetime | None) -> Header:
    return Header(ident(message, longest), str(message.get("From", "")), str(message.get("To", "")),
                  str(message.get("Subject", "")), _date(message, received), " ".join(text.split())[:snippet_chars],
                  labels, folder, unread, attachments)


def text_and_attachments(message: EmailMessage) -> tuple[str, tuple[Attachment, ...]]:
    """The body of a message as text, and its attachments by name, type and size."""
    plain: list[str] = []
    html: list[str] = []
    files: list[Attachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        data = part.get_payload(decode=True)
        raw = data if isinstance(data, bytes) else b""
        if name:
            files.append(Attachment(str(name), part.get_content_type(), len(raw)))
        elif part.get_content_type() == "text/plain":
            plain.append(_decoded(raw, part.get_content_charset()))
        elif part.get_content_type() == "text/html":
            html.append(_decoded(raw, part.get_content_charset()))
    text = "\n".join(plain) if plain else "\n".join(body.html_text(h) for h in html)
    return without_nul(text, "mail").strip(), tuple(files)


def full(message: EmailMessage, head: Header, body_chars: int) -> Message:
    text, files = text_and_attachments(message)
    kept = text[:body_chars]
    return Message(head, kept, len(kept) < len(text), files)


def _decoded(raw: bytes, charset: str | None) -> str:
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _date(message: EmailMessage, received: datetime | None) -> datetime:
    try:
        parsed = parsedate_to_datetime(str(message.get("Date", "")))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError, IndexError):
        return received or datetime.fromtimestamp(0, UTC)
