"""A fake Gmail at its HTTP boundary, with no import from `ashley`: `install` makes every `httpx2.AsyncClient` request go
to `FakeGmail.handle` instead of the network, and records it. Shapes follow Gmail's REST reference
(https://developers.google.com/gmail/api/reference/rest/v1/users.messages, .labels, users/getProfile) and its search
operators (https://support.google.com/mail/answer/7190):

- every call needs `Authorization: Bearer <token>`; an unknown or expired token is 401 `UNAUTHENTICATED`, an unknown
  message 404 `NOT_FOUND`, in Gmail's `{"error": {"code", "message", "status"}}` body;
- `messages.list` answers ids and thread ids only, newest first, `maxResults` at most 500 (100 when left out), a
  `nextPageToken` while more remain, no `messages` key at all when none match, and leaves out spam and trash;
- `messages.get` answers `format=minimal|metadata|full|raw`: `metadata` carries only the headers asked for in
  `metadataHeaders` and no parts, `full` the MIME tree with base64url (unpadded) bodies and attachments as ids and sizes;
- the search operators it understands are `from:` `to:` `subject:` `after:` `before:` `is:unread` `has:attachment`
  `label:` `in:` and plain words, each as `key:value`, `key:"two words"` or `key:(two words)`; anything else is 400, so
  an unsupported query surfaces instead of matching nothing.

The token endpoint answers the `refresh_token` grant as Google's does: the client authenticates, a refresh token it
never issued, or one it revoked, is `invalid_grant`, and a refresh answers no new refresh token."""

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import Header
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest

CLIENT_ID = "gcid-mail.apps.googleusercontent.test"
CLIENT_SECRET = "gsecret-mail-CLIENTSECRET"
API_HOSTS = ("gmail.googleapis.com", "www.googleapis.com")
TOKEN_HOST = "oauth2.googleapis.com"
MAX_RESULTS, DEFAULT_RESULTS = 500, 100
SYSTEM_LABELS = ("INBOX", "SENT", "DRAFT", "SPAM", "TRASH", "UNREAD", "STARRED", "IMPORTANT")


def b64(text: str) -> str:
    """Gmail's body encoding: base64url, left unpadded."""
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def encoded(text: str) -> str:
    """A header value as RFC 2047 encodes a non-ASCII one: `=?utf-8?b?...?=`."""
    return Header(text, "utf-8").encode()


@dataclass
class Msg:
    """One message in the fake mailbox. `labels` are Gmail label ids. `subject_header` is the Subject header as it is on
    the wire (an encoded word, say), `subject` what a person reads. `attachments` are (name, type, size)."""

    id: str
    subject: str
    sender: str
    to: str
    date: datetime
    labels: tuple[str, ...] = ("INBOX",)
    text: str | None = None
    html: str | None = None
    attachments: tuple[tuple[str, str, int], ...] = ()
    snippet: str = ""
    subject_header: str | None = None

    def header_list(self) -> list[dict[str, str]]:
        return [{"name": "From", "value": self.sender}, {"name": "To", "value": self.to},
                {"name": "Subject", "value": self.subject_header or self.subject},
                {"name": "Date", "value": self.date.strftime("%a, %d %b %Y %H:%M:%S +0000")},
                {"name": "Message-ID", "value": f"<{self.id}@mail.test>"}]

    def internal_ms(self) -> int:
        return int(self.date.timestamp() * 1000)

    def words(self) -> str:
        return " ".join(filter(None, (self.subject, self.snippet, self.text, _strip(self.html or "")))).lower()

    def _bodies(self) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for kind, content in (("text/plain", self.text), ("text/html", self.html)):
            if content is not None:
                parts.append({"partId": "", "mimeType": kind, "filename": "", "headers": [],
                              "body": {"size": len(content.encode()), "data": b64(content)}})
        return parts

    def payload(self, full: bool, wanted: set[str] | None) -> dict[str, Any]:
        headers = [h for h in self.header_list() if wanted is None or h["name"].lower() in wanted]
        if not full:
            return {"partId": "", "mimeType": "multipart/mixed", "filename": "", "headers": headers,
                    "body": {"size": 0}}
        bodies = self._bodies()
        top: dict[str, Any]
        if len(bodies) == 1 and not self.attachments:
            top = {**bodies[0], "headers": headers}
        else:
            alternative = {"partId": "0", "mimeType": "multipart/alternative", "filename": "", "headers": [],
                           "body": {"size": 0}, "parts": bodies} if len(bodies) > 1 else None
            inner = [alternative] if alternative else bodies
            top = {"partId": "", "mimeType": "multipart/mixed" if self.attachments else "multipart/alternative",
                   "filename": "", "headers": headers, "body": {"size": 0}, "parts": [*inner, *[
                       {"partId": str(i + 1), "mimeType": kind, "filename": name,
                        "headers": [{"name": "Content-Disposition", "value": f'attachment; filename="{name}"'}],
                        "body": {"attachmentId": f"att-{self.id}-{i}", "size": size}}
                       for i, (name, kind, size) in enumerate(self.attachments)]]}
        return top

    def resource(self, fmt: str, wanted: set[str] | None) -> dict[str, Any]:
        body: dict[str, Any] = {"id": self.id, "threadId": f"th-{self.id}", "labelIds": list(self.labels),
                                "snippet": self.snippet, "historyId": "1000", "internalDate": str(self.internal_ms()),
                                "sizeEstimate": 2048}
        if fmt == "raw":
            body["raw"] = b64("\r\n".join(f"{h['name']}: {h['value']}" for h in self.header_list()))
        elif fmt != "minimal":
            body["payload"] = self.payload(fmt == "full", wanted if fmt == "metadata" else None)
        return body


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


@dataclass(frozen=True)
class Seen:
    """One request the fake saw: `kind` is `token`, `gmail` or `stray`; `path` is after `/gmail/v1/users/<who>`."""

    kind: str
    method: str
    host: str
    path: str
    query: dict[str, list[str]]
    bearer: str
    form: dict[str, str]

    def one(self, name: str) -> str | None:
        return self.query[name][0] if name in self.query else None


@dataclass
class FakeGmail:
    """The mailbox `address` holds `messages` under `user_labels` (id to name). `valid` are the access tokens Gmail
    accepts (`expired` are refused, as one past its expiry is); `refresh_tokens` are the refresh tokens Google issued.
    `refuse_refresh`, `refresh_down` and `refresh_status` shape the refresh grant; `gmail_status` makes every Gmail
    call answer that status with its error body, `gmail_down` makes it unreachable, `gmail_code` is the `status` word of
    the error body; `in_refresh` runs once inside the first refresh, before it answers (another pod's whole call)."""

    address: str = "alana@gmail.test"
    messages: list[Msg] = field(default_factory=list[Msg])
    user_labels: dict[str, str] = field(default_factory=lambda: {"Label_12": "School", "Label_13": "Receipts"})
    valid: set[str] = field(default_factory=set[str])
    expired: set[str] = field(default_factory=set[str])
    refresh_tokens: set[str] = field(default_factory=set[str])
    expires_in: int = 3600
    refuse_refresh: bool = False
    refresh_down: bool = False
    refresh_status: int | None = None
    gmail_status: int | None = None
    gmail_code: str = "UNAVAILABLE"
    gmail_down: bool = False
    in_refresh: Callable[[], Any] | None = None
    seen: list[Seen] = field(default_factory=list[Seen])
    issued: list[str] = field(default_factory=list[str])
    counter: int = 0

    def add(self, *msgs: Msg) -> None:
        self.messages.extend(msgs)

    def accept(self, access: str, refresh: str) -> None:
        """What a connection made before the test holds: Gmail takes `access`, Google's token endpoint takes `refresh`."""
        self.valid.add(access)
        self.refresh_tokens.add(refresh)

    def calls(self, kind: str) -> list[Seen]:
        return [s for s in self.seen if s.kind == kind]

    def bearers(self) -> list[str]:
        return [s.bearer for s in self.calls("gmail")]

    def secret_values(self) -> set[str]:
        """Every credential this fake saw or issued: what no log, result or stored plaintext may carry."""
        return {CLIENT_SECRET, *self.valid, *self.expired, *self.refresh_tokens, *self.issued}

    def private_text(self) -> set[str]:
        """What a log line must never carry: addresses, subjects, bodies, snippets, label names."""
        found = {self.address, *self.user_labels.values()}
        for m in self.messages:
            found.update({m.subject, m.sender, m.to, m.snippet, *(x for x in (m.text, m.html) if x)})
        return {x for x in found if x}

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        host, path = request.url.host, request.url.path
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        auth = request.headers.get("authorization", "")
        bearer = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        query = parse_qs(request.url.query.decode())
        kind = "token" if host == TOKEN_HOST and path.endswith("/token") else \
            "gmail" if host in API_HOSTS and path.startswith("/gmail/v1/users/") else "stray"
        rest = "/" + path.split("/", 5)[5] if kind == "gmail" and path.count("/") >= 5 else path
        self.seen.append(Seen(kind, request.method, host, rest, query, bearer, form))
        if kind == "token":
            return await self._token(request, form)
        if kind == "gmail":
            return self._gmail(request, rest, query, bearer)
        return httpx2.Response(404, json={})

    @staticmethod
    def _error(status: int, text: str, code: str) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"code": status, "message": text, "status": code}})

    def _gmail(self, request: httpx2.Request, path: str, query: dict[str, list[str]], bearer: str) -> httpx2.Response:
        if self.gmail_down:
            raise httpx2.ConnectError("gmail is down")
        if bearer not in self.valid or bearer in self.expired:
            return self._error(401, "Request had invalid authentication credentials.", "UNAUTHENTICATED")
        if self.gmail_status is not None:
            return self._error(self.gmail_status, "refused by the fake", self.gmail_code)
        if request.method != "GET":
            return self._error(405, "this fake serves reads only", "FAILED_PRECONDITION")
        if path == "/profile":
            return httpx2.Response(200, json={"emailAddress": self.address, "messagesTotal": len(self.messages),
                                              "threadsTotal": len(self.messages), "historyId": "1000"})
        if path == "/labels":
            return httpx2.Response(200, json={"labels": self._labels()})
        if path == "/messages":
            return self._list(query)
        found = re.fullmatch(r"/messages/([^/]+)", path)
        if found:
            return self._get(found.group(1), query)
        return self._error(404, "Not Found", "NOT_FOUND")

    def _labels(self) -> list[dict[str, str]]:
        system = [{"id": i, "name": i, "type": "system", "messageListVisibility": "show"} for i in SYSTEM_LABELS]
        mine = [{"id": i, "name": n, "type": "user", "messageListVisibility": "show", "labelListVisibility":
                 "labelShow"} for i, n in self.user_labels.items()]
        return system + mine

    def _get(self, ident: str, query: dict[str, list[str]]) -> httpx2.Response:
        found = next((m for m in self.messages if m.id == ident), None)
        if found is None:
            return self._error(404, "Requested entity was not found.", "NOT_FOUND")
        wanted = {h.lower() for h in query.get("metadataHeaders", [])} or None
        return httpx2.Response(200, json=found.resource(query.get("format", ["full"])[0], wanted))

    def _list(self, query: dict[str, list[str]]) -> httpx2.Response:
        try:
            size = min(int(query.get("maxResults", [str(DEFAULT_RESULTS)])[0]), MAX_RESULTS)
            start = int(query["pageToken"][0].removeprefix("pt-")) if "pageToken" in query else 0
            matched = self._search(query.get("q", [""])[0], query.get("labelIds", []),
                                   query.get("includeSpamTrash", ["false"])[0] == "true")
        except ValueError as e:
            return self._error(400, str(e), "INVALID_ARGUMENT")
        body: dict[str, Any] = {"resultSizeEstimate": len(matched)}
        page = matched[start:start + size]
        if page:
            body["messages"] = [{"id": m.id, "threadId": f"th-{m.id}"} for m in page]
        if start + size < len(matched):
            body["nextPageToken"] = f"pt-{start + size}"
        return httpx2.Response(200, json=body)

    def _search(self, q: str, label_ids: list[str], spam_trash: bool) -> list[Msg]:
        terms = list(_terms(q))
        found = [m for m in self.messages if (spam_trash or not {"SPAM", "TRASH"} & set(m.labels))
                 and all(i in m.labels for i in label_ids) and all(self._matches(m, *t) for t in terms)]
        return sorted(found, key=lambda m: (m.internal_ms(), m.id), reverse=True)

    def _label_names(self, msg: Msg) -> set[str]:
        names = {_slug(self.user_labels.get(i, i)) for i in msg.labels}
        return names | {i.lower() for i in msg.labels}

    def _matches(self, m: Msg, key: str | None, value: str) -> bool:
        want = value.lower()
        if key is None:
            return all(w in m.words() for w in want.split())
        if key in ("from", "to"):
            return all(w in (m.sender if key == "from" else m.to).lower() for w in want.split())
        if key == "subject":
            return all(w in m.subject.lower() for w in want.split())
        if key in ("after", "before"):
            moment = _moment(want)
            return m.date.timestamp() >= moment if key == "after" else m.date.timestamp() < moment
        if key == "is":
            return self._is(m, want)
        if key == "has":
            if want != "attachment":
                raise ValueError(f"unsupported operator has:{want}")
            return bool(m.attachments)
        if key == "label":
            return _slug(want) in self._label_names(m)
        if key == "in":
            return want == "anywhere" or want in self._label_names(m)
        raise ValueError(f"unsupported operator {key}:")

    @staticmethod
    def _is(m: Msg, want: str) -> bool:
        if want in ("unread", "read"):
            return ("UNREAD" in m.labels) == (want == "unread")
        raise ValueError(f"unsupported operator is:{want}")

    async def _token(self, request: httpx2.Request, form: dict[str, str]) -> httpx2.Response:
        if request.method != "POST":
            return self._error(405, "invalid_request", "INVALID")
        auth = request.headers.get("authorization", "")
        said = base64.b64decode(auth[6:]).decode() if auth.startswith("Basic ") else \
            f"{form.get('client_id')}:{form.get('client_secret')}"
        if said != f"{CLIENT_ID}:{CLIENT_SECRET}":
            return httpx2.Response(401, json={"error": "invalid_client"})
        if form.get("grant_type") != "refresh_token":
            return httpx2.Response(400, json={"error": "unsupported_grant_type"})
        if self.refresh_down:
            raise httpx2.ConnectError("the token endpoint is down")
        if self.refresh_status is not None:
            return httpx2.Response(self.refresh_status, json={"error": "temporarily_unavailable"})
        if form.get("refresh_token") not in self.refresh_tokens or self.refuse_refresh:
            return httpx2.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired"})
        hook, self.in_refresh = self.in_refresh, None
        if hook is not None:
            await hook()
        self.counter += 1
        access = f"at-new-{self.counter}-ACCESSTOKEN"
        self.valid.add(access)
        self.issued.append(access)
        return httpx2.Response(200, content=json.dumps({"access_token": access, "expires_in": self.expires_in,
                                                        "token_type": "Bearer", "scope": "openid email"}).encode(),
                               headers={"content-type": "application/json"})

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every `httpx2.AsyncClient` of the process, however built, reaches this fake instead of the network."""
        transport = httpx2.MockTransport(self.handle)

        def transport_for(_: httpx2.AsyncClient, __: httpx2.URL) -> httpx2.AsyncBaseTransport:
            return transport

        monkeypatch.setattr(httpx2.AsyncClient, "_transport_for_url", transport_for)


_TERM = re.compile(r'(?:(\w+):)?(?:\(([^)]*)\)|"([^"]*)"|(\S+))')


def _terms(q: str):
    for m in _TERM.finditer(q):
        key, grouped, quoted, bare = m.groups()
        yield key.lower() if key else None, grouped if grouped is not None else quoted if quoted is not None else bare


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def _moment(text: str) -> float:
    if text.isdigit() and len(text) > 8:
        return float(text)
    return datetime.strptime(text.replace("-", "/"), "%Y/%m/%d").replace(tzinfo=UTC).timestamp()
