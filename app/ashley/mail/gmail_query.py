"""A `MailQuery` as Gmail's `q` search string (https://support.google.com/mail/answer/7190). Every value is cut to
words with the characters that mean something in a search (quotes, brackets, a leading minus) removed, so a value can
narrow a search and never add an operator."""

from .model import MailQuery

FOLDERS = {"inbox": "inbox", "sent": "sent", "drafts": "drafts", "spam": "spam", "trash": "trash"}
"""Folder names as `Mailbox.labels` gives them, to Gmail's `in:` values."""
_BARE = str.maketrans("", "", "\"(){}\\:")


def words(value: str) -> list[str]:
    """`value`'s words with search syntax removed; none when nothing is left."""
    found = [w.lstrip("-") for w in value.translate(_BARE).split()]
    return [w for w in found if w and w.upper() not in ("OR", "AND")]


def _grouped(operator: str, value: str) -> list[str]:
    found = words(value)
    return [f"{operator}:({' '.join(found)})"] if found else []


def _label(value: str) -> list[str]:
    found = words(value)
    return [f'label:"{" ".join(found)}"'] if found else []


def search_string(query: MailQuery) -> str:
    """The `q` for `query`; empty when it asks nothing."""
    terms = _grouped("from", query.sender) + _grouped("to", query.to) + _grouped("subject", query.subject)
    terms += words(query.text)
    if query.after is not None:
        terms.append("after:" + query.after.strftime("%Y/%m/%d"))
    if query.before is not None:
        terms.append("before:" + query.before.strftime("%Y/%m/%d"))
    folder = query.folder.strip().lower()
    terms += [f"in:{FOLDERS[folder]}"] if folder in FOLDERS else _label(query.folder)
    terms += _label(query.label)
    if query.unread is not None:
        terms.append("is:unread" if query.unread else "is:read")
    if query.has_attachment is not None:
        terms.append("has:attachment" if query.has_attachment else "-has:attachment")
    return " ".join(terms)
