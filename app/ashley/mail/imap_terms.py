"""A `MailQuery` as IMAP `SEARCH` criteria (RFC 3501, 6.4.4). Values are cut to words with the characters that mean
something in a search removed, so a value can narrow a search and never add a key. A word with a character outside
ASCII goes as a UTF-8 literal, which IMAP allows once per command, so each such word is a search of its own and the
answers are intersected (`imap_wire.Imap.search`). `has_attachment` is not a criterion IMAP has; the adapter filters on
the message."""

from dataclasses import dataclass
from datetime import date

from .model import MailQuery

_BARE = str.maketrans("", "", "\"(){}\\")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Criteria:
    """`plain` is every criterion that fits one command, as the words IMAP takes (values quoted); `literals` the
    (key, value) pairs that each need a command of their own."""

    plain: tuple[str, ...] = ()
    literals: tuple[tuple[str, str], ...] = ()


def terms(value: str) -> list[str]:
    """`value`'s words with search syntax removed; none when nothing is left."""
    return [w for w in value.translate(_BARE).split() if w]


def day(value: date) -> str:
    return f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year}"


def quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def criteria(query: MailQuery) -> Criteria:
    """The criteria for `query`; empty when it asks nothing."""
    plain: list[str] = []
    literals: list[tuple[str, str]] = []
    for key, value in (("FROM", query.sender), ("TO", query.to), ("SUBJECT", query.subject), ("TEXT", query.text)):
        for word in terms(value):
            if word.isascii():
                plain += [key, quote(word)]
            else:
                literals.append((key, word))
    if query.after is not None:
        plain += ["SINCE", day(query.after)]
    if query.before is not None:
        plain += ["BEFORE", day(query.before)]
    if query.unread is not None:
        plain.append("UNSEEN" if query.unread else "SEEN")
    return Criteria(tuple(plain), tuple(literals))
