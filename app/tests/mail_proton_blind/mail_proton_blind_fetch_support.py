"""What a fake Bridge answers to IMAP SEARCH and FETCH (RFC 3501 sections 6.4.4 and 6.4.5), with no import from `ashley`:
the search keys a client may use, evaluated over a mailbox, and the fetch items (FLAGS, UID, INTERNALDATE, RFC822.SIZE,
ENVELOPE, BODYSTRUCTURE, BODY, RFC822 and its parts, and `BODY[<section>]<partial>` with PEEK) rendered from the message's bytes.
Hand-written from the RFC; unverified against Bridge."""

import re
from collections.abc import Callable
from datetime import date, datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime

from mail_proton_blind_store_support import Copy, crlf

Token = str | list["Token"]
Pred = Callable[[Copy, int], bool]


def text_of(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def header_text(msg: Message, name: str) -> str:
    return " ".join(text_of(str(v)) for v in msg.get_all(name, []))


def body_text(msg: Message) -> str:
    parts: list[str] = []
    for part in msg.walk():
        if part.get_content_maintype() == "text" and not part.get_filename():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
    return "\n".join(parts)


def seqset(spec: str, top: int) -> set[int]:
    out: set[int] = set()
    for piece in spec.split(","):
        lo, _, hi = piece.partition(":")
        a = top if lo == "*" else int(lo)
        b = a if not hi else (top if hi == "*" else int(hi))
        out |= set(range(min(a, b), max(a, b) + 1))
    return out


def _day(msg: Message) -> date | None:
    try:
        return parsedate_to_datetime(str(msg.get("Date", ""))).date()
    except (TypeError, ValueError):
        return None


def _imap_day(text: str) -> date:
    return datetime.strptime(text.strip('"'), "%d-%b-%Y").date()


class Searcher:
    """Parses search keys (already tokenised) into a predicate over (copy, sequence number)."""

    def __init__(self, tokens: list[Token], top: int) -> None:
        self.t = list(tokens)
        self.top = top
        if len(self.t) >= 2 and isinstance(self.t[0], str) and self.t[0].upper() == "CHARSET":
            del self.t[:2]

    def parse(self) -> Pred:
        preds: list[Pred] = []
        while self.t:
            preds.append(self.key())
        return lambda c, n: all(p(c, n) for p in preds)

    def word(self) -> str:
        token = self.t.pop(0)
        assert isinstance(token, str)
        return token

    def key(self) -> Pred:
        token = self.t.pop(0)
        if isinstance(token, list):
            return Searcher(token, self.top).parse()
        k = token.upper()
        if k == "NOT":
            inner = self.key()
            return lambda c, n: not inner(c, n)
        if k == "OR":
            a, b = self.key(), self.key()
            return lambda c, n: a(c, n) or b(c, n)
        if re.fullmatch(r"[0-9*:,]+", k):
            return lambda c, n, s=seqset(k, self.top): n in s
        return self.simple(k)

    def simple(self, k: str) -> Pred:
        flags = {"SEEN": "\\Seen", "ANSWERED": "\\Answered", "FLAGGED": "\\Flagged", "DELETED": "\\Deleted",
                 "DRAFT": "\\Draft"}
        if k == "ALL":
            return lambda c, n: True
        if k in flags:
            return lambda c, n, f=flags[k]: f in c.flags
        if k.startswith("UN") and k[2:] in flags:
            return lambda c, n, f=flags[k[2:]]: f not in c.flags
        if k in ("NEW", "RECENT"):
            return lambda c, n: False
        if k == "OLD":
            return lambda c, n: True
        return self.valued(k)

    def valued(self, k: str) -> Pred:
        if k == "UID":
            ids = seqset(self.word(), 10**9)
            return lambda c, n: c.uid in ids
        if k in ("KEYWORD", "UNKEYWORD"):
            kw = self.word()
            return lambda c, n: (kw in c.flags) == (k == "KEYWORD")
        if k == "HEADER":
            name, value = self.word(), self.word().lower()
            return lambda c, n: value in header_text(c.mail.parsed(), name).lower()
        if k in ("LARGER", "SMALLER"):
            size = int(self.word())
            return lambda c, n: (len(c.mail.raw) > size) == (k == "LARGER")
        value = self.word()
        if k in ("SINCE", "BEFORE", "ON", "SENTSINCE", "SENTBEFORE", "SENTON"):
            return self.dated(k, _imap_day(value))
        needle = value.lower()
        if k in ("FROM", "TO", "CC", "BCC", "SUBJECT"):
            return lambda c, n: needle in header_text(c.mail.parsed(), k.title()).lower()
        if k == "BODY":
            return lambda c, n: needle in body_text(c.mail.parsed()).lower()
        if k == "TEXT":
            return lambda c, n: needle in (header_text(c.mail.parsed(), "From") + header_text(c.mail.parsed(), "To")
                                           + header_text(c.mail.parsed(), "Subject") + body_text(c.mail.parsed())).lower()
        raise ValueError(f"unsupported search key {k}")

    def dated(self, k: str, wanted: date) -> Pred:
        def day(c: Copy) -> date | None:
            return _day(c.mail.parsed()) if k.startswith("SENT") else c.mail.idate.date()

        def test(c: Copy, n: int) -> bool:
            d = day(c)
            if d is None:
                return False
            if k.endswith("SINCE"):
                return d >= wanted
            if k.endswith("BEFORE"):
                return d < wanted
            return d == wanted

        return test


# --- fetch ------------------------------------------------------------------------------------------------------------


def quoted(value: str | None) -> str:
    if value is None:
        return "NIL"
    raw = value.encode("utf-8")
    if b"\r" in raw or b"\n" in raw or b'"' in raw or b"\\" in raw or any(b > 127 for b in raw):
        return "{%d}\r\n%s" % (len(raw), value)
    return f'"{value}"'


def addresses(msg: Message, name: str) -> str:
    found = getaddresses([str(v) for v in msg.get_all(name, [])])
    if not found:
        return "NIL"
    items: list[str] = []
    for display, addr in found:
        local, _, host = addr.partition("@")
        items.append(f"({quoted(display or None)} NIL {quoted(local)} {quoted(host or None)})")
    return "(" + "".join(items) + ")"


def envelope(msg: Message) -> str:
    def raw(name: str) -> str | None:
        return str(msg[name]) if name in msg else None

    return ("(" + " ".join([quoted(raw("Date")), quoted(raw("Subject")), addresses(msg, "From"), addresses(msg, "Sender"),
                            addresses(msg, "Reply-To"), addresses(msg, "To"), addresses(msg, "Cc"), addresses(msg, "Bcc"),
                            quoted(raw("In-Reply-To")), quoted(raw("Message-ID"))]) + ")")


def payload_bytes(part: Message) -> bytes:
    payload = part.get_payload(decode=False)
    if isinstance(payload, list):
        return b""
    return crlf(str(payload).encode("utf-8", errors="surrogateescape"))


def as_message(value: object) -> Message | None:
    return message_from_bytes(value.as_bytes()) if isinstance(value, Message) else None


def children(part: Message) -> list[Message]:
    found: list[Message] = []
    if part.is_multipart():
        for index in range(len(part.get_payload())):
            child = as_message(part.get_payload(index))
            if child is not None:
                found.append(child)
    return found


def structure(part: Message, extended: bool) -> str:
    if part.is_multipart():
        kids = "".join(structure(p, extended) for p in children(part))
        tail = f' ("BOUNDARY" {quoted(part.get_boundary())}) NIL NIL NIL' if extended else ""
        return f'({kids} "{part.get_content_subtype().upper()}"{tail})'
    given: list[tuple[str, str]] = list(part.get_params() or [])
    params = " ".join(f"{quoted(k.upper())} {quoted(v)}" for k, v in given[1:])
    enc = str(part.get("Content-Transfer-Encoding", "7bit")).upper()
    size = len(payload_bytes(part))
    base = (f'"{part.get_content_maintype().upper()}" "{part.get_content_subtype().upper()}" '
            f'{"(" + params + ")" if params else "NIL"} NIL NIL "{enc}" {size}')
    if part.get_content_maintype() == "text":
        base += f" {payload_bytes(part).count(b'\n')}"
    if not extended:
        return f"({base})"
    name = part.get_filename()
    how = str(part.get_content_disposition() or "attachment").upper()
    disposition = f'("{how}" ("FILENAME" {quoted(name)}))' if name else "NIL"
    return f"({base} NIL {disposition} NIL NIL)"


def split(raw: bytes) -> tuple[bytes, bytes]:
    head, sep, body = raw.partition(b"\r\n\r\n")
    return head + sep, body


def section(raw: bytes, spec: str) -> bytes:
    """The bytes `BODY[spec]` names: '' the whole message, HEADER, TEXT, HEADER.FIELDS (...) , and numbered parts."""
    head, body = split(raw)
    s = spec.strip()
    upper = s.upper()
    if not s:
        return raw
    if upper == "HEADER":
        return head
    if upper == "TEXT":
        return body
    if upper.startswith("HEADER.FIELDS"):
        names = {n.lower() for n in re.findall(r"[\w-]+", s[s.index("(") + 1:s.index(")")])}
        keep = upper.startswith("HEADER.FIELDS.NOT")
        lines = re.split(rb"\r\n(?![ \t])", head.rstrip(b"\r\n"))
        chosen = [ln for ln in lines if (ln.split(b":", 1)[0].decode().strip().lower() in names) != keep]
        return b"\r\n".join(chosen) + b"\r\n\r\n"
    return numbered(message_from_bytes(raw), s)


def numbered(msg: Message, spec: str) -> bytes:
    found = re.fullmatch(r"([\d.]*?)\.?(MIME|HEADER|TEXT)?", spec.upper())
    if found is None:
        raise ValueError(f"unsupported section {spec}")
    path, tail = found.group(1), found.group(2)
    part = msg
    for n in [int(x) for x in path.split(".") if x]:
        if part.is_multipart():
            part = children(part)[n - 1]
        elif n != 1:
            raise IndexError(spec)
    if tail == "MIME":
        return crlf(b"".join(f"{k}: {v}\r\n".encode() for k, v in list[tuple[str, str]](part.items())) + b"\r\n")
    return payload_bytes(part) if not part.is_multipart() else b""


def literal(data: bytes) -> bytes:
    return b"{%d}\r\n" % len(data) + data


def item(copy: Copy, name: str, seq_flags: Callable[[Copy], str]) -> tuple[bytes, bool]:
    """One fetch item rendered as `NAME value`, and whether it set `\\Seen`."""
    mail, up = copy.mail, name.upper()
    msg = mail.parsed()
    if up == "UID":
        return b"UID %d" % copy.uid, False
    if up == "FLAGS":
        return b"FLAGS " + seq_flags(copy).encode(), False
    if up == "INTERNALDATE":
        return b'INTERNALDATE "%s"' % mail.idate.strftime("%d-%b-%Y %H:%M:%S +0000").encode(), False
    if up == "RFC822.SIZE":
        return b"RFC822.SIZE %d" % len(mail.raw), False
    if up == "ENVELOPE":
        return b"ENVELOPE " + envelope(msg).encode("utf-8"), False
    if up in ("BODYSTRUCTURE", "BODY"):
        return up.encode() + b" " + structure(msg, up == "BODYSTRUCTURE").encode("utf-8"), False
    plain = {"RFC822": "", "RFC822.HEADER": "HEADER", "RFC822.TEXT": "TEXT"}
    if up in plain:
        return up.encode() + b" " + literal(section(mail.raw, plain[up])), up != "RFC822.HEADER"
    m = re.fullmatch(r"BODY(\.PEEK)?\[(.*)\](<\d+\.\d+>)?", name, re.IGNORECASE | re.DOTALL)
    if m is None:
        raise ValueError(f"unsupported fetch item {name}")
    data = section(mail.raw, m.group(2))
    label = f"BODY[{m.group(2)}]"
    if m.group(3):
        start, count = (int(x) for x in m.group(3)[1:-1].split("."))
        data, label = data[start:start + count], f"{label}<{start}>"
    return label.encode() + b" " + literal(data), m.group(1) is None
