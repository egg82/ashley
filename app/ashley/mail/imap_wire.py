"""IMAP to Bridge over `imaplib`: one blocking session (`Imap`) that a caller runs in a thread. It knows the wire and
nothing about what a message means: folders, searching, fetching, flags, copying and appending, with every answer turned
to plain values. A refused login is `needs_reconnect`; a connection that cannot be made, a certificate that is not the
pod's, a timeout or a reply that is not IMAP is `unreachable`; a command Bridge answers NO or BAD to is `refused`."""

import imaplib
import re
import ssl
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import imap_names, proton_endpoint
from .imap_terms import Criteria, quote
from .model import MailFailed

_CHUNK = 100
_RECORD = re.compile(rb"^\d+ \(")
_UID = re.compile(rb"\bUID (\d+)")
_FLAGS = re.compile(rb"\bFLAGS \(([^)]*)\)")
_DATE = re.compile(rb'\bINTERNALDATE "([^"]+)"')


@dataclass(frozen=True)
class Fetched:
    """One message of a FETCH answer: its `uid`, `flags` (lower case), the time Bridge `received` it (None when the
    answer carried none) and the text asked for, `body`."""

    uid: int
    flags: frozenset[str]
    received: datetime | None
    body: bytes


class Imap:
    def __init__(self, conn: imaplib.IMAP4) -> None:
        self._conn = conn
        self._selected = ""

    @classmethod
    def open(cls, login: proton_endpoint.Login, timeout_s: float) -> "Imap":
        """A session signed in as `login.address`, at the first host that accepts a connection. Raises MailFailed."""
        for host in login.hosts:
            try:
                conn = imaplib.IMAP4(host, login.imap_port, timeout=timeout_s)
            except (OSError, imaplib.IMAP4.error):
                continue
            session = cls(conn)
            try:
                session._secure(login)
            except MailFailed:
                session.close()
                raise
            return session
        raise MailFailed("unreachable")

    def _secure(self, login: proton_endpoint.Login) -> None:
        try:
            self._conn.starttls(proton_endpoint.context())
            proton_endpoint.pinned(self._conn.sock, login.fingerprint)
        except (imaplib.IMAP4.error, OSError, ssl.SSLError) as e:
            raise MailFailed("unreachable") from e
        try:
            self._conn.login(login.address, login.password)
        except imaplib.IMAP4.abort as e:
            raise MailFailed("unreachable") from e
        except imaplib.IMAP4.error as e:
            raise MailFailed("needs_reconnect") from e
        except (OSError, ssl.SSLError) as e:
            raise MailFailed("unreachable") from e

    def close(self) -> None:
        try:
            self._conn.shutdown()
        except (OSError, imaplib.IMAP4.error):
            pass

    def folders(self) -> tuple[str, ...]:
        """Every folder that can be selected, by name."""
        data = self._ok("LIST", self._conn.list)
        names: list[str] = []
        for item in data:
            head, literal = _split(item)
            name = imap_names.listed(head, literal if isinstance(item, tuple) else None)
            if name is not None:
                names.append(name)
        return tuple(names)

    def select(self, folder: str, readonly: bool = True) -> None:
        self._ok("SELECT", lambda: self._conn.select(imap_names.quoted(folder), readonly))
        self._selected = folder

    def search(self, folder: str, criteria: Criteria) -> list[int]:
        """The uids in `folder` matching every criterion, ascending."""
        self.select(folder)
        found = self._uids(("ALL",) if not criteria.plain else criteria.plain, None)
        for key, value in criteria.literals:
            found &= self._uids(("CHARSET", "UTF-8", key), value.encode())
        return sorted(found)

    def header_search(self, folder: str, name: str, value: str) -> list[int]:
        """The uids in `folder` whose header `name` contains `value`."""
        self.select(folder)
        if value.isascii():
            return sorted(self._uids(("HEADER", name, quote(value)), None))
        return sorted(self._uids(("CHARSET", "UTF-8", "HEADER", name), value.encode()))

    def fetch(self, folder: str, uids: Sequence[int], what: str) -> list[Fetched]:
        """`what` (a `BODY.PEEK[...]` item) of each uid in `folder`, with its flags and receipt time, in uid order."""
        self.select(folder)
        out: list[Fetched] = []
        for start in range(0, len(uids), _CHUNK):
            chunk = ",".join(str(u) for u in uids[start:start + _CHUNK])
            out += _fetched(self._ok("FETCH", lambda: self._conn.uid("FETCH", chunk, f"(UID FLAGS INTERNALDATE{' ' + what if what else ''})")))
        return sorted(out, key=lambda f: f.uid)

    def received(self, folder: str, uids: Sequence[int]) -> dict[int, datetime]:
        """When Bridge received each uid, for those it says."""
        return {f.uid: f.received for f in self.fetch(folder, uids, "") if f.received is not None}

    def flag(self, folder: str, uid: int, flag: str, on: bool) -> None:
        self.select(folder, readonly=False)
        self._ok("STORE", lambda: self._conn.uid("STORE", str(uid), "+FLAGS.SILENT" if on else "-FLAGS.SILENT",
                                                  f"({flag})"))

    def copy(self, folder: str, uid: int, target: str) -> None:
        self.select(folder, readonly=False)
        self._ok("COPY", lambda: self._conn.uid("COPY", str(uid), imap_names.quoted(target)))

    def delete(self, folder: str, uid: int) -> None:
        """Remove `uid` from `folder` (for Bridge: take the message out of that folder or label)."""
        self.flag(folder, uid, "\\Deleted", True)
        self._ok("EXPUNGE", self._conn.expunge)

    def append(self, folder: str, flags: str, message: bytes) -> None:
        self._ok("APPEND", lambda: self._conn.append(imap_names.quoted(folder), flags, None, message))

    def _uids(self, args: Iterable[str], literal: bytes | None) -> set[int]:
        setattr(self._conn, "literal", literal)
        data = self._ok("SEARCH", lambda: self._conn.uid("SEARCH", *args))
        first = data[0] if data else b""
        return {int(n) for n in (first.split() if isinstance(first, bytes) else [])}

    def _ok(self, command: str, call: Any) -> list[Any]:
        try:
            status, data = call()
        except (OSError, ssl.SSLError, imaplib.IMAP4.abort) as e:
            raise MailFailed("unreachable") from e
        except imaplib.IMAP4.error as e:
            raise MailFailed("refused") from e
        if status != "OK":
            raise MailFailed("refused")
        return list(data or [])


def _is_pair(item: object) -> bool:
    return isinstance(item, tuple) and item.__len__() == 2


def _split(item: Any) -> tuple[bytes, bytes]:
    """An imaplib data item as its line and its literal (empty for an item that is a line alone)."""
    if _is_pair(item):
        first, second = item
        return (first, second) if isinstance(first, bytes) and isinstance(second, bytes) else (b"", b"")
    return (item, b"") if isinstance(item, bytes) else (b"", b"")


def _fetched(data: list[Any]) -> list[Fetched]:
    """The messages of a FETCH answer. imaplib hands each as a tuple of the line up to a literal and the literal, followed by
    whatever the line carried after it, so a record is its pieces up to the next line that begins one."""
    records: list[list[bytes]] = []
    for item in data:
        head, literal = _split(item)
        if _RECORD.match(head) or not records:
            records.append([head, b""])
        else:
            records[-1][0] += b" " + head
        records[-1][1] += literal
    out: list[Fetched] = []
    for line, body in records:
        uid, flags, when = _UID.search(line), _FLAGS.search(line), _DATE.search(line)
        if uid is None:
            continue
        out.append(Fetched(int(uid.group(1)), frozenset(f.lower() for f in (flags.group(1).decode().split() if flags else [])),
                           _received(when.group(1).decode()) if when else None, body))
    return out


def _received(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), "%d-%b-%Y %H:%M:%S %z").astimezone(UTC)
    except ValueError:
        return None
