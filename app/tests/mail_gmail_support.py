"""A fake Gmail behind `httpx2.MockTransport`, answering `users/me/{profile,labels,messages,messages/{id}}` and the three POSTs below, in the
shapes of Gmail's API reference (developers.google.com/workspace/gmail/api/reference/rest/v1/). Verified against the
reference pages: the list answer (`messages[]` of `id` and `threadId`, `nextPageToken`, `resultSizeEstimate`), the
`q`, `maxResults` and `pageToken` parameters, and the Message and MessagePart fields (`id`, `labelIds`, `snippet`,
`internalDate` as a string of epoch milliseconds, `payload` with `mimeType`, `filename`, `headers`, `body`, `parts`).
Changes (`users.drafts.create` body `{message: {raw, threadId?}}` answering a Draft `{id, message}`;
`users.messages.send` body `{raw, threadId?}` answering a Message; `users.messages.batchModify` body `{ids, addLabelIds,
removeLabelIds}` answering 204 with no body) are verified against the same pages. Unverified, hand-written: that
`batchModify` accepts the `TRASH` and `SPAM` system labels as ids to add; the 400 for a recipient Gmail refuses; that
`format=metadata` answers headers with no body data and the part tree with no data;
the profile and label list answers (`emailAddress`; `labels[]` of `id`, `name`, `type`); the `Content-Type` header of a
part carrying its charset; a 400 for an id Gmail does not recognise. Nothing here was captured from Google."""

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import httpx2
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Connection, Listed, Needs, Opened, Resource, ResourceKind
from ashley.connections.renewal import Renewal
from ashley.connections.resources import ConnectionResources, Usable, Use, permits
from ashley.google.kind import GMAIL_MODIFY, GOOGLE
from ashley.mail import config as mail_config
from ashley.mail.gmail import GmailMailbox
from ashley.mail.gmail_wire import GmailWire
from ashley.mail.mailbox import Mailbox
from money_support import EPOCH, HeldConnections

TOKEN = "ya29.fake-access-token"
ADDRESS = "alana@gmail.test"
HOME, ALANA, SAM = 1, 7, 8
LABELS: list[dict[str, str]] = [
    {"id": "INBOX", "name": "INBOX", "type": "system"}, {"id": "SENT", "name": "SENT", "type": "system"},
    {"id": "UNREAD", "name": "UNREAD", "type": "system"}, {"id": "CATEGORY_UPDATES", "name": "CATEGORY_UPDATES", "type": "system"},
    {"id": "Label_7", "name": "School", "type": "user"}]


def b64(text: str, charset: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip("=")


def part(mime: str, text: str = "", charset: str = "utf-8", **fields: Any) -> dict[str, Any]:
    headers = [{"name": "Content-Type", "value": f'{mime}; charset="{charset}"'}]
    return {"mimeType": mime, "filename": "", "headers": headers,
            "body": {"size": len(text), "data": b64(text, charset)} if text else {"size": 0}, **fields}


def message(id_: str, subject: str, millis: int, labels: tuple[str, ...] = ("INBOX",), body: dict[str, Any] | None = None,
            sender: str = "Pat <pat@school.test>") -> dict[str, Any]:
    headers = [{"name": "From", "value": sender}, {"name": "To", "value": ADDRESS},
               {"name": "Subject", "value": subject}, {"name": "Date", "value": "x"}, {"name": "Message-ID", "value": "<m>"}]
    inner = body or part("text/plain", f"body of {subject}")
    payload = {"partId": "", **inner, "headers": [*inner["headers"], *headers]}
    return {"id": id_, "threadId": "t" + id_, "labelIds": list(labels), "snippet": f"snippet {subject}",
            "internalDate": str(millis), "sizeEstimate": 1000, "payload": payload}


@dataclass
class FakeGmail:
    """`messages` newest first; `down` is a status every call answers; `gone` ids are listed but answer 404 when read; `seen` is (path, query, authorization)."""

    messages: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    down: int | None = None
    garbage: bool = False
    gone: set[str] = field(default_factory=set[str])
    next_page: str = ""
    posted: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, dict[str, Any]]])
    post_status: int | None = None
    seen: list[tuple[str, dict[str, list[str]], str]] = field(default_factory=list[tuple[str, dict[str, list[str]], str]])

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        query: dict[str, list[str]] = {}
        for key, value in request.url.params.multi_items():
            query.setdefault(key, []).append(value)
        auth = request.headers.get("authorization", "")
        self.seen.append((path, query, auth))
        if request.method == "POST":
            return self._post(path, auth, request.content)
        if self.down is not None:
            return httpx2.Response(self.down)
        if auth != f"Bearer {TOKEN}":
            return httpx2.Response(401, json={"error": {"code": 401}})
        if self.garbage:
            return httpx2.Response(200, content=b"<html>not json")
        return self._route(path, query)

    def _post(self, path: str, auth: str, content: bytes) -> httpx2.Response:
        if auth != f"Bearer {TOKEN}":
            return httpx2.Response(401, json={"error": {"code": 401}})
        sent: dict[str, Any] = json.loads(content)
        self.posted.append((path, sent))
        if self.post_status is not None:
            return httpx2.Response(self.post_status)
        if path == "/drafts":
            return httpx2.Response(200, json={"id": "d1", "message": {"id": "dm1", "threadId": "t1"}})
        if path == "/messages/send":
            return httpx2.Response(200, json={"id": "s1", "threadId": sent.get("threadId", "t1"), "labelIds": ["SENT"]})
        if path == "/messages/batchModify":
            for m in self.messages:
                if m["id"] in sent["ids"]:
                    kept = [l for l in m["labelIds"] if l not in sent["removeLabelIds"]]
                    m["labelIds"] = kept + [l for l in sent["addLabelIds"] if l not in kept]
            return httpx2.Response(204)
        return httpx2.Response(404)

    def _route(self, path: str, query: dict[str, list[str]]) -> httpx2.Response:
        if path == "/profile":
            return httpx2.Response(200, json={"emailAddress": ADDRESS, "messagesTotal": 3, "threadsTotal": 3})
        if path == "/labels":
            return httpx2.Response(200, json={"labels": LABELS})
        if path == "/messages":
            cap = int(query.get("maxResults", ["100"])[0])
            listed: dict[str, Any] = {"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in self.messages[:cap]],
                                      "resultSizeEstimate": len(self.messages)}
            if self.next_page:
                listed["nextPageToken"] = self.next_page
            return httpx2.Response(200, json=listed)
        found = next((m for m in self.messages if path == "/messages/" + m["id"]), None)
        if found is None or found["id"] in self.gone:
            return httpx2.Response(404, json={"error": {"code": 404}})
        if query.get("format") == ["metadata"]:
            wanted = {h.lower() for h in query.get("metadataHeaders", [])}
            headers = [h for h in found["payload"]["headers"] if h["name"].lower() in wanted]
            return httpx2.Response(200, json={**found, "payload": {"partId": "", "mimeType": "multipart/mixed",
                                                                   "headers": headers}})
        return httpx2.Response(200, json=found)


@dataclass
class FakeRenewal(Renewal):
    """Hands out `TOKEN`, or raises what `fails` is."""

    fails: Exception | None = None
    asked: list[int] = field(default_factory=list[int])
    opened_for: list[int | None] = field(default_factory=list[int | None])

    async def access_token(self, connection_id: int, household_id: int, person_id: int | None = None) -> str | None:
        self.asked.append(connection_id)
        self.opened_for.append(person_id)
        if self.fails is not None:
            raise self.fails
        return TOKEN


@dataclass
class HeldResources(ConnectionResources):
    """The one mailbox (`ADDRESS`) of each held connection, kept unless its id is in `shared` or the connection is the
    household's, gated by the real policy (`permits`); the speaker is a member of the household whenever named."""

    held: HeldConnections
    shared: set[int] = field(default_factory=set[int])

    def _boxes(self) -> list[tuple[Connection, Resource]]:
        return [(o.connection, Resource(ADDRESS, "mailbox", ADDRESS, o.connection.id in self.shared or o.connection.person_id is None))
                for o in self.held.held.values()]

    async def of_household(self, household_id: int, person_id: int | None = None) -> dict[int, tuple[Resource, ...]]:
        return {c.id: (r,) for c, r in self._boxes()}

    async def listed(self, connection_id: int, household_id: int, found: Sequence[Listed]) -> tuple[Resource, ...]:
        return ()

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str,
                    shared: bool) -> Resource | None:
        return None

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        member = use.speaker_id is not None
        return tuple(Usable(c, r) for c, r in self._boxes() if permits(use, changing, c, r, member))


def wire(gmail: FakeGmail, **changed: int) -> mail_config.MailConfig:
    """Register the real adapter over `gmail`, the fake renewal and the Google kind; returns the config in use, the
    shipped one with `changed` settings."""
    config = replace(mail_config.load(), **changed)
    http = httpx2.AsyncClient(transport=gmail.transport(), follow_redirects=False)
    services.register(Mailbox, GmailMailbox(GmailWire(http, 5, config.message_bytes), config))
    services.register(Renewal, FakeRenewal())
    services.register(ConnectionKinds, ConnectionKinds((GOOGLE,)))
    return config


def connect(person: int | None = ALANA, scopes: tuple[str, ...] = ("openid", "email", GMAIL_MODIFY),
            needs: Needs | None = None, held: HeldConnections | None = None, label: str = "",
            shared: bool = False) -> HeldConnections:
    """A Google connection of `person` (the household's when None) with `scopes`, its mailbox `shared` or kept, added to
    `held` and registered as Connections and, over it, ConnectionResources."""
    held = held if held is not None else HeldConnections()
    n = len(held.held) + 1
    connection = Connection(n, HOME, "google", "https://www.googleapis.com", ALANA, EPOCH, EPOCH, person, label, needs,
                            scopes)
    held.held[(HOME, f"google{n}")] = Opened(connection, "refresh-token")
    services.register(Connections, held)
    known = services.get(ConnectionResources)
    resources = known if isinstance(known, HeldResources) and known.held is held else HeldResources(held)
    if shared:
        resources.shared.add(n)
    services.register(ConnectionResources, resources)
    return held
