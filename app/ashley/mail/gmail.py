"""Gmail as a Mailbox (https://developers.google.com/workspace/gmail/api/guides): the connection's access token, from
`ashley.connections.renewal.Renewal`, sent as a bearer. A message id is Gmail's own. Read-only scopes are enough for
every read here, and `gmail.modify` for drafting, sending and changing (it includes the reads). A search lists ids, then reads each one's headers, and its folder and labels are named from the
mailbox's own label list; the household's labels are the user labels, and the system ones show as `folder` and
`unread`."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.errors import HeaderParseError
from email.header import decode_header, make_header

from .. import services
from ..connections.connections import ConnectionsUnavailable
from ..connections.oauth import OAuthUnavailable
from ..connections.renewal import NeedsReconnect, Renewal
from . import body, calls
from .config import MailConfig
from .gmail_change import label_ids
from .gmail_compose import raw_message
from .gmail_query import FOLDERS, search_string
from .gmail_shapes import DraftShape, Empty, LabelList, LabelShape, MessageList, MessageShape, Profile
from .gmail_wire import GmailWire
from .mailbox import Mailbox
from .model import Account, Draft, Header, Label, MailChange, MailFailed, MailQuery, Message, Page, Target
from .targets import shown

_READ_SCOPES = frozenset({"gmail.readonly", "gmail.modify"})
_CHANGE_SCOPES = frozenset({"gmail.modify"})
_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
_JUNK = frozenset({"SPAM", "CATEGORY_PROMOTIONS"})
"""The labels Gmail itself puts on a message it filed as spam or as promotions."""
_FOLDER_LABELS = {"INBOX": "inbox", "SENT": "sent", "DRAFT": "drafts", "SPAM": "spam", "TRASH": "trash"}


class GmailMailbox(Mailbox):
    def __init__(self, wire: GmailWire, config: MailConfig) -> None:
        self._wire = wire
        self._config = config

    def can_read(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return any(s.rsplit("/", 1)[-1] in _READ_SCOPES or s == "https://mail.google.com/" for s in scopes)

    def can_change(self, kind: str, scopes: tuple[str, ...]) -> bool:
        return any(s.rsplit("/", 1)[-1] in _CHANGE_SCOPES or s == "https://mail.google.com/" for s in scopes)

    async def address(self, account: Account) -> str:
        async def work(token: str) -> tuple[str, int]:
            return (await self._wire.get(token, "/profile", {}, Profile)).emailAddress, 1
        return await self._timed("address", account, work)

    async def labels(self, account: Account) -> tuple[Label, ...]:
        async def work(token: str) -> tuple[tuple[Label, ...], int]:
            found = (await self._label_list(token)).labels
            folders = [Label(_FOLDER_LABELS[l.id], True) for l in found if l.id in _FOLDER_LABELS]
            users = [Label(l.name, False) for l in found if l.type == "user"]
            kept = tuple(folders + users)[:self._config.labels_max]
            return kept, len(kept)
        return await self._timed("labels", account, work)

    async def search(self, account: Account, query: MailQuery) -> Page[Header]:
        async def work(token: str) -> tuple[Page[Header], int]:
            names = await self._names(token)
            params: dict[str, str | int | list[str]] = {"maxResults": self._config.search_max}
            for key, value in (("q", search_string(query)), ("pageToken", query.page)):
                if value:
                    params[key] = value
            listed = await self._wire.get(token, "/messages", params, MessageList)
            refs = listed.messages[:self._config.search_max]
            got = await asyncio.gather(*(self._header(token, r.id, names) for r in refs), return_exceptions=True)
            failed = next((e for e in got if isinstance(e, MailFailed) and e.reason != "not_found"), None)
            if failed is not None:
                raise failed
            headers = tuple(h for h in got if isinstance(h, Header))
            return Page(headers, bool(listed.nextPageToken), listed.nextPageToken), len(headers)
        return await self._timed("search", account, work)

    async def read(self, account: Account, message_id: str) -> Message:
        async def work(token: str) -> tuple[Message, int]:
            if not _valid_id(message_id, self._config):
                raise MailFailed("not_found")
            names = await self._names(token)
            shape = await self._wire.get(token, f"/messages/{message_id}", {"format": "full"}, MessageShape)
            text, files = body.text_and_attachments(shape.payload)
            kept = text[:self._config.body_chars]
            return Message(_header(shape, names, self._config.snippet_chars, len(files)), kept,
                           len(kept) < len(text), files), 1
        return await self._timed("read", account, work)

    async def draft(self, account: Account, draft: Draft) -> str:
        async def work(token: str) -> tuple[str, int]:
            made = await self._wire.post(token, "/drafts", {"message": await self._composed(token, draft)}, DraftShape)
            return made.id, 1
        return await self._timed("draft", account, work)

    async def send(self, account: Account, draft: Draft) -> str:
        async def work(token: str) -> tuple[str, int]:
            sent = await self._wire.post(token, "/messages/send", await self._composed(token, draft), MessageShape)
            return sent.id, 1
        return await self._timed("send", account, work)

    async def change(self, account: Account, targets: tuple[Target, ...], change: MailChange) -> int:
        async def work(token: str) -> tuple[int, int]:
            add, remove = label_ids(change, await self._names(token))
            wanted = list({t.id: t for t in targets}.values())
            if not wanted or not (add or remove):
                raise MailFailed("refused")
            if not all(_valid_id(t.id, self._config) for t in wanted):
                raise MailFailed("not_found")
            found = await asyncio.gather(*(self._found(token, t.id) for t in wanted), return_exceptions=True)
            failed = next((e for e in found if isinstance(e, MailFailed)), None)
            if failed is not None:
                raise failed
            if not all(isinstance(f, MessageShape) and _is_shown(f, t) for f, t in zip(found, wanted, strict=True)):
                raise MailFailed("refused")
            await self._wire.post(token, "/messages/batchModify",
                                  {"ids": [t.id for t in wanted], "addLabelIds": add, "removeLabelIds": remove}, Empty)
            return len(wanted), len(wanted)
        return await self._timed("change", account, work)

    async def junk(self, account: Account, targets: tuple[Target, ...]) -> bool:
        async def work(token: str) -> tuple[bool, int]:
            wanted = list({t.id: t for t in targets}.values())
            if not wanted or not all(_valid_id(t.id, self._config) for t in wanted):
                return False, 0
            found = await asyncio.gather(*(self._found(token, t.id) for t in wanted), return_exceptions=True)
            failed = next((e for e in found if isinstance(e, MailFailed) and e.reason != "not_found"), None)
            if failed is not None:
                raise failed
            marked = all(isinstance(f, MessageShape) and _is_shown(f, t) and not _JUNK.isdisjoint(f.labelIds)
                         for f, t in zip(found, wanted, strict=True))
            return marked, len(wanted)
        return await self._timed("junk", account, work)

    async def _composed(self, token: str, draft: Draft) -> dict[str, str]:
        """The `raw` (and `threadId`) Gmail takes for `draft`, threaded under the message it answers."""
        if not draft.reply_to:
            return {"raw": raw_message(draft)}
        if not _valid_id(draft.reply_to, self._config):
            raise MailFailed("not_found")
        original = await self._wire.get(token, f"/messages/{draft.reply_to}",
                                        {"format": "metadata", "metadataHeaders": ["Message-ID", "References"]},
                                        MessageShape)
        wanted = {h.name.lower(): h.value for h in original.payload.headers}
        return {"raw": raw_message(draft, wanted.get("message-id", ""), wanted.get("references", "")),
                "threadId": original.threadId}

    async def _found(self, token: str, message_id: str) -> MessageShape:
        return await self._wire.get(token, f"/messages/{message_id}",
                                    {"format": "metadata", "metadataHeaders": ["From", "Subject"]}, MessageShape)

    async def _header(self, token: str, message_id: str, names: dict[str, LabelShape]) -> Header:
        shape = await self._wire.get(token, f"/messages/{message_id}", {"format": "full"}, MessageShape)
        return _header(shape, names, self._config.snippet_chars, len(body.text_and_attachments(shape.payload)[1]))

    async def _label_list(self, token: str) -> LabelList:
        return await self._wire.get(token, "/labels", {}, LabelList)

    async def _names(self, token: str) -> dict[str, LabelShape]:
        return {l.id: l for l in (await self._label_list(token)).labels}

    async def _timed[T](self, call: str, account: Account, work: Callable[[str], Awaitable[tuple[T, int]]]) -> T:
        async def run() -> tuple[T, int]:
            return await work(await _token(account))

        return await calls.logged(call, account, run)


async def _token(account: Account) -> str:
    try:
        token = await services.get(Renewal).access_token(account.connection_id, account.household_id, account.person_id)
    except NeedsReconnect:
        raise MailFailed("needs_reconnect") from None
    except (OAuthUnavailable, ConnectionsUnavailable) as e:
        raise MailFailed("unreachable") from e
    if token is None:
        raise MailFailed("refused")
    return token


def _header(shape: MessageShape, names: dict[str, LabelShape], snippet_chars: int, attachments: int) -> Header:
    wanted = {h.name.lower(): h.value for h in shape.payload.headers}
    system = {_FOLDER_LABELS[i] for i in shape.labelIds if i in _FOLDER_LABELS}
    folder = next((n for n in FOLDERS if n in system), "")
    users = tuple(names[i].name for i in shape.labelIds if i in names and names[i].type == "user")
    return Header(shape.id, wanted.get("from", ""), wanted.get("to", ""), _decoded(wanted.get("subject", "")),
                  _date(shape.internalDate), shape.snippet[:snippet_chars], users, folder, "UNREAD" in shape.labelIds,
                  attachments)


def _valid_id(message_id: str, config: MailConfig) -> bool:
    return bool(message_id) and len(message_id) <= config.message_id_chars and set(message_id) <= _ID_CHARS


def _is_shown(shape: MessageShape, target: Target) -> bool:
    wanted = {h.name.lower(): h.value for h in shape.payload.headers}
    return shown(wanted.get("from", ""), target.sender) and shown(_decoded(wanted.get("subject", "")), target.subject)


def _decoded(value: str) -> str:
    """An RFC 2047 encoded-word header as its text."""
    try:
        return str(make_header(decode_header(value)))
    except (HeaderParseError, UnicodeError, LookupError):
        return value


def _date(millis: str) -> datetime:
    try:
        return datetime.fromtimestamp(int(millis) / 1000, UTC)
    except (ValueError, OverflowError, OSError):
        return datetime.fromtimestamp(0, UTC)
