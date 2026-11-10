"""A fake Gmail at its HTTP boundary for the changes suite, with no import from `ashley`: `install` makes every
`httpx2.AsyncClient` request go to `FakeGmail.handle` instead of the network, and records it. Shapes follow Gmail's REST
reference (https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages, .drafts, .labels):

- reads: `getProfile`, `labels.list`, `messages.list` (ids newest first, no `messages` key when none), `messages.get`
  (`full` and `metadata`, base64url unpadded bodies);
- writes: `messages.send` and `drafts.create` take `{"raw": <base64url RFC 822>, "threadId"?}` (a draft as
  `{"message": {...}}`), `drafts.send` takes `{"id"}`, `messages.modify` takes `{"addLabelIds", "removeLabelIds"}`,
  `messages.batchModify` takes `{"ids", "addLabelIds", "removeLabelIds"}`, `messages.trash` and `untrash` take nothing;
  an unknown label id is 400 `INVALID_ARGUMENT`, an unknown message 404 `NOT_FOUND`;
- a write with a token the fake was not told may write is 403 `PERMISSION_DENIED` (Gmail answers `insufficientPermissions`
  to a token whose scopes lack the call);
- permanent deletion (`DELETE`, `messages.batchDelete`), `labels.create` and every other path are recorded in `forbidden`
  and answered 403, so a test can say they never happened;
- every call needs `Authorization: Bearer <token>`; an unknown token is 401 `UNAUTHENTICATED`, in Gmail's
  `{"error": {"code", "message", "status"}}` body.

A sent or drafted message is what the raw bytes parse to (`email.policy.default`): addresses, subject, body and the
threading headers are read back from them, so what a test compares is what Gmail would have delivered."""

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest

API_HOSTS = ("gmail.googleapis.com", "www.googleapis.com")
SYSTEM_LABELS = ("INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "UNREAD", "STARRED", "IMPORTANT")


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


@dataclass
class Msg:
    """One message in the fake mailbox; `labels` are Gmail label ids."""

    id: str
    subject: str
    sender: str
    to: str
    date: datetime
    labels: list[str] = field(default_factory=lambda: ["INBOX"])
    text: str = ""
    snippet: str = ""
    subject_header: str | None = None

    def header_list(self) -> list[dict[str, str]]:
        return [{"name": "From", "value": self.sender}, {"name": "To", "value": self.to},
                {"name": "Subject", "value": self.subject_header or self.subject},
                {"name": "Date", "value": self.date.strftime("%a, %d %b %Y %H:%M:%S +0000")},
                {"name": "Message-ID", "value": f"<{self.id}@mail.test>"}]

    def internal_ms(self) -> int:
        return int(self.date.timestamp() * 1000)

    def resource(self, fmt: str) -> dict[str, Any]:
        body: dict[str, Any] = {"id": self.id, "threadId": f"th-{self.id}", "labelIds": list(self.labels),
                                "snippet": self.snippet, "historyId": "1000", "internalDate": str(self.internal_ms()),
                                "sizeEstimate": 2048}
        if fmt != "minimal":
            part: dict[str, Any] = {"partId": "", "mimeType": "text/plain", "filename": "",
                                    "headers": self.header_list(), "body": {"size": len(self.text), "data": b64(self.text)}}
            body["payload"] = part if fmt == "full" else {**part, "body": {"size": 0}}
        return body


@dataclass(frozen=True)
class Seen:
    """One request the fake saw: `kind` is `gmail` or `stray`; `path` is after `/gmail/v1/users/<who>`."""

    kind: str
    method: str
    path: str
    query: dict[str, list[str]]
    bearer: str
    body: dict[str, Any]


@dataclass(frozen=True)
class Stored:
    """A message the mailbox was given by `send` or `drafts.create`, as its raw bytes parse."""

    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    subject: str
    body: str
    in_reply_to: str
    references: str
    thread_id: str
    header_names: tuple[str, ...]
    via: str


def _addresses(parsed: EmailMessage, name: str) -> tuple[str, ...]:
    found: list[str] = []
    for value in parsed.get_all(name, []):
        found.extend(a.addr_spec for a in getattr(value, "addresses", ()))
    return tuple(found)


def parse_raw(raw: str, thread_id: str, via: str) -> Stored:
    data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    parsed = message_from_bytes(data, policy=policy.default)
    assert isinstance(parsed, EmailMessage)
    part = parsed.get_body(("plain", "html"))
    text = part.get_content() if part is not None else ""
    return Stored(_addresses(parsed, "To"), _addresses(parsed, "Cc"), _addresses(parsed, "Bcc"),
                  str(parsed.get("Subject", "")), str(text).replace("\r\n", "\n").rstrip("\r\n"), str(parsed.get("In-Reply-To", "")),
                  str(parsed.get("References", "")), thread_id, tuple(k.lower() for k in parsed.keys()), via)


@dataclass
class FakeGmail:
    """The mailbox `address` holds `messages` under `user_labels` (id to name). `valid` are the access tokens Gmail
    accepts and `writers` those that may write; `gmail_status` makes every write answer that status; `gmail_down` makes
    every call unreachable. `sent` and `drafts` are what the mailbox was given; `forbidden` the calls that must never
    happen."""

    address: str = "alana@gmail.test"
    messages: list[Msg] = field(default_factory=list[Msg])
    user_labels: dict[str, str] = field(default_factory=lambda: {"Label_12": "School", "Label_13": "Receipts"})
    valid: set[str] = field(default_factory=set[str])
    writers: set[str] = field(default_factory=set[str])
    refresh_tokens: set[str] = field(default_factory=set[str])
    gmail_status: int | None = None
    gmail_down: bool = False
    seen: list[Seen] = field(default_factory=list[Seen])
    sent: list[Stored] = field(default_factory=list[Stored])
    drafts: list[Stored] = field(default_factory=list[Stored])
    forbidden: list[Seen] = field(default_factory=list[Seen])
    counter: int = 0

    def add(self, *msgs: Msg) -> None:
        self.messages.extend(msgs)

    def accept(self, access: str, refresh: str, may_write: bool) -> None:
        self.valid.add(access)
        self.refresh_tokens.add(refresh)
        if may_write:
            self.writers.add(access)

    def calls(self, kind: str) -> list[Seen]:
        return [s for s in self.seen if s.kind == kind]

    def writes(self) -> list[Seen]:
        return [s for s in self.calls("gmail") if s.method != "GET"]

    def labels_of(self, ident: str) -> set[str]:
        return set(next(m for m in self.messages if m.id == ident).labels)

    def bearers(self) -> list[str]:
        return [s.bearer for s in self.calls("gmail")]

    def secret_values(self) -> set[str]:
        return {*self.valid, *self.refresh_tokens}

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        host, path = request.url.host, request.url.path
        auth = request.headers.get("authorization", "")
        bearer = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        kind = "gmail" if host in API_HOSTS and path.startswith("/gmail/v1/users/") else "stray"
        rest = "/" + path.split("/", 5)[5] if kind == "gmail" and path.count("/") >= 5 else path
        body = _json(request.content)
        seen = Seen(kind, request.method, rest, parse_qs(request.url.query.decode()), bearer, body)
        self.seen.append(seen)
        if kind != "gmail":
            return httpx2.Response(404, json={})
        if self.gmail_down:
            raise httpx2.ConnectError("gmail is down")
        if bearer not in self.valid:
            return self._error(401, "Request had invalid authentication credentials.", "UNAUTHENTICATED")
        return self._gmail(seen)

    @staticmethod
    def _error(status: int, text: str, code: str) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"code": status, "message": text, "status": code}})

    def _gmail(self, s: Seen) -> httpx2.Response:
        if s.method == "GET":
            return self._read(s)
        if s.bearer not in self.writers:
            return self._error(403, "Request had insufficient authentication scopes.", "PERMISSION_DENIED")
        if self.gmail_status is not None:
            return self._error(self.gmail_status, "refused by the fake", "UNAVAILABLE")
        return self._write(s)

    def _read(self, s: Seen) -> httpx2.Response:
        if s.path == "/profile":
            return httpx2.Response(200, json={"emailAddress": self.address, "messagesTotal": len(self.messages),
                                              "threadsTotal": len(self.messages), "historyId": "1000"})
        if s.path == "/labels":
            system = [{"id": i, "name": i, "type": "system"} for i in SYSTEM_LABELS]
            mine = [{"id": i, "name": n, "type": "user", "labelListVisibility": "labelShow"}
                    for i, n in self.user_labels.items()]
            return httpx2.Response(200, json={"labels": system + mine})
        if s.path == "/messages":
            live = [m for m in self.messages if not {"SPAM", "TRASH"} & set(m.labels)]
            found = sorted(live, key=lambda m: (m.internal_ms(), m.id), reverse=True)
            body: dict[str, Any] = {"resultSizeEstimate": len(found)}
            if found:
                body["messages"] = [{"id": m.id, "threadId": f"th-{m.id}"} for m in found]
            return httpx2.Response(200, json=body)
        got = re.fullmatch(r"/messages/([^/]+)", s.path)
        if got is not None:
            return self._get(got.group(1), s.query.get("format", ["full"])[0])
        return self._forbid(s)

    def _get(self, ident: str, fmt: str) -> httpx2.Response:
        found = next((m for m in self.messages if m.id == ident), None)
        if found is None:
            return self._error(404, "Requested entity was not found.", "NOT_FOUND")
        return httpx2.Response(200, json=found.resource(fmt))

    def _forbid(self, s: Seen) -> httpx2.Response:
        self.forbidden.append(s)
        return self._error(403, "the fake does not allow this call", "PERMISSION_DENIED")

    def _write(self, s: Seen) -> httpx2.Response:
        if s.method != "POST":
            return self._forbid(s)
        if s.path == "/messages/send":
            return self._store(self.sent, s.body, "send", "SENT")
        if s.path == "/drafts":
            return self._store(self.drafts, s.body.get("message", {}), "draft", "DRAFT")
        if s.path == "/messages/batchModify":
            return self._modify(list(s.body.get("ids", [])), s.body)
        got = re.fullmatch(r"/messages/([^/]+)/(modify|trash|untrash)", s.path)
        if got is None:
            return self._forbid(s)
        ident, action = got.groups()
        change = {"trash": {"addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
                  "untrash": {"addLabelIds": ["INBOX"], "removeLabelIds": ["TRASH"]}}.get(action, s.body)
        return self._modify([ident], change)

    def _store(self, into: list[Stored], body: dict[str, Any], via: str, label: str) -> httpx2.Response:
        raw = body.get("raw")
        if not isinstance(raw, str) or not raw:
            return self._error(400, "Invalid value for ByteString", "INVALID_ARGUMENT")
        self.counter += 1
        thread = str(body.get("threadId") or f"th-new-{self.counter}")
        into.append(parse_raw(raw, thread, via))
        message = {"id": f"new-{self.counter}", "threadId": thread, "labelIds": [label]}
        return httpx2.Response(200, json=message if via == "send" else {"id": f"r-{self.counter}", "message": message})

    def _modify(self, ids: list[str], change: dict[str, Any]) -> httpx2.Response:
        add, remove = list(change.get("addLabelIds", [])), list(change.get("removeLabelIds", []))
        known = {*SYSTEM_LABELS, *self.user_labels}
        if not set(add + remove) <= known:
            return self._error(400, "Invalid label", "INVALID_ARGUMENT")
        found = [m for m in self.messages if m.id in ids]
        if len(found) != len(set(ids)):
            return self._error(404, "Requested entity was not found.", "NOT_FOUND")
        for m in found:
            m.labels = [x for x in m.labels if x not in remove] + [x for x in add if x not in m.labels]
        return httpx2.Response(200, json={"id": ids[0], "labelIds": found[0].labels} if len(ids) == 1 else {})

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every `httpx2.AsyncClient` of the process, however built, reaches this fake instead of the network."""
        transport = httpx2.MockTransport(self.handle)

        def transport_for(_: httpx2.AsyncClient, __: httpx2.URL) -> httpx2.AsyncBaseTransport:
            return transport

        monkeypatch.setattr(httpx2.AsyncClient, "_transport_for_url", transport_for)


def _json(content: bytes) -> dict[str, Any]:
    try:
        loaded: Any = json.loads(content) if content else {}
    except ValueError:
        return {}
    loose: Any = loaded
    return dict[str, Any](loose) if isinstance(loaded, dict) else {}


def moment(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)
