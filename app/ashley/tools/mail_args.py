"""The arguments of her mail tools, as the model sent them, made into the port's records. Shapes only: a bad one raises
`BadArguments` naming the argument, never its value."""

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from ..mail.config import MailConfig
from ..mail.model import MOVES, Draft, MailChange, MailQuery, Target
from .bench_args import BadArguments

ADDRESS_MAX = 320
TEXT_MAX = 200
CURSOR_MAX = 500
RECIPIENT_MAX = 120
SHOWN_MAX = 100
LABEL_NAME_MAX = 60
LABELS_MAX = 4
_ADDRESS = re.compile(r"[^\s<>(),;:\"\\@\x00-\x1f]+@[^\s<>(),;:\"\\@\x00-\x1f]+")
_FLAGS = ("unread", "has_attachment")


def text(args: Mapping[str, object], name: str, longest: int = TEXT_MAX) -> str:
    """The optional string argument `name`, stripped; '' when left out."""
    value = args.get(name, "")
    if not isinstance(value, str) or "\x00" in value or len(value) > longest:
        raise BadArguments(f"{name} is an optional string of at most {longest} characters")
    return value.strip()


def message_id(args: Mapping[str, object], longest: int) -> str:
    value = text(args, "id", longest)
    if not value:
        raise BadArguments("id is a message's id as mail_search gives it")
    return value


def start(args: Mapping[str, object]) -> int:
    value = args.get("start", 0)
    if type(value) is not int or value < 0:
        raise BadArguments("start is a whole number of characters, 0 or more")
    return value


def _day(args: Mapping[str, object], name: str) -> date | None:
    value = text(args, name, 10)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BadArguments(f"{name} is a day as YYYY-MM-DD") from None


def _flag(args: Mapping[str, object], name: str) -> bool | None:
    value = args.get(name)
    if value is not None and type(value) is not bool:
        raise BadArguments(f"{name} is true or false")
    return value


def query(args: Mapping[str, object]) -> MailQuery:
    """The search the arguments ask for."""
    flags = {name: _flag(args, name) for name in _FLAGS}
    return MailQuery(sender=text(args, "from"), to=text(args, "to"), subject=text(args, "subject"),
                     text=text(args, "text"), after=_day(args, "after"), before=_day(args, "before"),
                     folder=text(args, "folder"), label=text(args, "label"), page=text(args, "page", CURSOR_MAX),
                     **flags)


def _list(args: Mapping[str, object], name: str, most: int, what: str) -> list[object]:
    value = args.get(name, [])
    loose: Any = value
    if not isinstance(value, list) or len(loose) > most:
        raise BadArguments(f"{name} is a list of at most {most} {what}")
    return list[object](loose)


def _addresses(args: Mapping[str, object], name: str, most: int) -> tuple[str, ...]:
    found = [a.strip() if isinstance(a, str) else None for a in _list(args, name, most, "addresses")]
    if not all(a is not None and len(a) <= RECIPIENT_MAX and _ADDRESS.fullmatch(a) for a in found):
        raise BadArguments(f"{name} holds plain addresses such as name@example.com, none over {RECIPIENT_MAX} characters")
    return tuple(a for a in found if a is not None)


def draft(args: Mapping[str, object], config: MailConfig) -> Draft:
    """The message `mail_draft` and `mail_send` ask for. The subject is one line and the body not empty, at most
    `MailConfig.max_body_chars`."""
    to, cc = _addresses(args, "to", config.max_recipients), _addresses(args, "cc", config.max_recipients)
    subject, body = text(args, "subject"), args.get("body")
    if not to or len(to) + len(cc) > config.max_recipients:
        raise BadArguments(f"to and cc together hold one to {config.max_recipients} addresses, to at least one")
    if "\n" in subject or "\r" in subject:
        raise BadArguments("subject is one line")
    if not isinstance(body, str) or not body.strip() or "\x00" in body or len(body) > config.max_body_chars:
        raise BadArguments(f"body is the message's text, not empty, at most {config.max_body_chars} characters")
    return Draft(to, subject, body, cc, text(args, "reply_to", config.message_id_chars))


def _shown(entry: Mapping[str, object], name: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str) or len(value) > SHOWN_MAX or "\x00" in value:
        raise BadArguments(f"each message's {name} is as mail_search showed it, cut to its first {SHOWN_MAX} characters")
    return value


def targets(args: Mapping[str, object], config: MailConfig) -> tuple[Target, ...]:
    """The messages `mail_label` names, each with the sender and subject it was shown with."""
    found: list[Target] = []
    for entry in _list(args, "messages", config.max_change_ids, "messages"):
        loose: Any = entry
        if not isinstance(entry, dict) or set[object](loose) - {"id", "from", "subject"}:
            raise BadArguments("each message is an object of id, from and subject")
        item = dict[str, object](loose)
        ident = item.get("id")
        if not isinstance(ident, str) or not ident or len(ident) > config.message_id_chars:
            raise BadArguments("each message's id is as mail_search gave it")
        found.append(Target(ident, _shown(item, "from"), _shown(item, "subject")))
    if not found:
        raise BadArguments(f"messages lists one to {config.max_change_ids} messages")
    return tuple(found)


def _names(args: Mapping[str, object], name: str) -> tuple[str, ...]:
    found = [n.strip() if isinstance(n, str) else "" for n in _list(args, name, LABELS_MAX, "label names")]
    if not all(n and len(n) <= LABEL_NAME_MAX and "\x00" not in n for n in found):
        raise BadArguments(f"{name} holds label names as mail_labels gives them, none over {LABEL_NAME_MAX} characters")
    return tuple(found)


def change(args: Mapping[str, object]) -> MailChange:
    """What `mail_label` does to each message; at least one of its parts is given."""
    folder = text(args, "folder", 20).lower()
    if folder and folder not in MOVES:
        raise BadArguments(f"folder is one of {', '.join(MOVES)}")
    done = MailChange(_names(args, "add"), _names(args, "remove"), folder, _flag(args, "unread"))
    if done.empty:
        raise BadArguments("a change names something to do: add, remove, folder or unread")
    return done
