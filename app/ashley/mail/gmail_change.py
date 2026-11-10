"""A `MailChange` as Gmail's `users.messages.batchModify` body
(https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/batchModify): label ids to add and
remove. The household's labels are named by their user labels only, so a system label (`TRASH`, `SPAM`, `INBOX`,
`UNREAD`) cannot be reached by a name; folders and read state are the system labels the change names itself."""

from collections.abc import Mapping

from .gmail_shapes import LabelShape
from .model import MailChange, MailFailed

_MOVES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "inbox": (("INBOX",), ("SPAM", "TRASH")), "archive": ((), ("INBOX", "SPAM", "TRASH")),
    "spam": (("SPAM",), ("INBOX", "TRASH")), "trash": (("TRASH",), ("INBOX", "SPAM"))}


def label_ids(change: MailChange, names: Mapping[str, LabelShape]) -> tuple[list[str], list[str]]:
    """The label ids to add and to remove. Raises MailFailed `not_found` for a label name that is none of the mailbox's
    user labels, `refused` for a folder that is not one it moves to or for a label both added and removed."""
    users = {l.name.lower(): l.id for l in names.values() if l.type == "user"}
    add, remove = _named(change.add, users), _named(change.remove, users)
    if set(add) & set(remove):
        raise MailFailed("refused")
    if change.folder:
        if change.folder not in _MOVES:
            raise MailFailed("refused")
        moved_in, moved_out = _MOVES[change.folder]
        add, remove = add + list(moved_in), remove + list(moved_out)
    if change.unread is not None:
        (add if change.unread else remove).append("UNREAD")
    return _once(add), _once([r for r in remove if r not in add])


def _named(wanted: tuple[str, ...], users: Mapping[str, str]) -> list[str]:
    found = [users.get(n.strip().lower()) for n in wanted]
    if None in found:
        raise MailFailed("not_found")
    return [f for f in found if f is not None]


def _once(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))
