"""Blind contract tests for the mail port and Gmail's read tools (decisions.md, "Her mail is a port with two adapters, and
Proton's runs as a leased Bridge", build part 2): the real app on a real database, a fake Gmail at its HTTP boundary
(`mail_gmail_blind_fake_support`), and the turn's tools as `ashley.channels.turn_tools.for_turn` offers them. Everything
the design does not name is guessed once, in ASSUMPTIONS below; a test never guesses on its own. The same list, with the
design sentence under each, is in `~/scratch/ashley/mail/gmail-blind/assumptions.txt`.

ASSUMPTIONS (each with the design sentence it rests on):

A1  The tools are `mail_boxes`, `mail_labels`, `mail_search`, `mail_read`, offered by `for_turn` as a source. Rests on the
    tools table and "`planned:ashley.tools.mail.MailTools`, added per turn by `for_turn`".
A2  A mailbox is named by its address in the argument `mailbox`. Rests on "name a mailbox by its address, never a
    connection id".
A3  A Gmail mailbox's address is what Gmail's `users.getProfile` answers (`emailAddress`), stored as the mailbox
    resource's ref when the connection is stored (`connect` below stores it as the connect flow does), so naming a
    mailbox the turn may not use reaches no Gmail. Rests on "name a mailbox by its address" and part 3's resources.
A4  A successful tool result is JSON text. A failure is `is_error` with the reason's name (`needs_reconnect`,
    `unreachable`, `refused`, `not_found`) in the text. Rests on "Failures are `MailFailed(reason)`" and "her tools over
    it answer `needs_reconnect`".
A5  Result keys are found by name anywhere in the JSON (`dig`), so wrappers (`messages`, `header`) are free. The names:
    a header has `id`, `from`, `to`, `subject`, `date`, `snippet`, `labels`, `folder`, `unread` and an attachment count
    under `attachments` or `attachment_count`; a message adds `body` and `attachments` as a list of `name`, `type`,
    `size`; a search carries `cut` and `next_page`; a read carries `start`, `next_start` and `total_chars`. Rests on
    the records' field lists in "The mail port and her tools" and on `git_read_file`'s paging, which the read copies.
A6  A search takes `MailQuery`'s fields as arguments named `from`, `to`, `subject`, `text`, `after`, `before`, `folder`,
    `label`, `unread`, `has_attachment`, `page`; dates as `YYYY-MM-DD`; `page` is the `next_page` the last answer gave.
    Rests on "`MailQuery` (from, to, subject words, text words, after, before, folder, label, unread, has attachment,
    page)".
A7  `date` in a header is ISO 8601 and starts with the message's calendar date in UTC. Rests on `Header` carrying a date.
A8  A header's `labels` name user labels as the household named them, never Gmail's label ids; `folder` of an inbox
    message is `inbox` in any case; `unread` is a boolean from Gmail's UNREAD label. Rests on "each is the only code that
    reads its provider's field names" and "`mail_labels`: a mailbox's folders and labels, set up by the household".
A9  `mail_labels` lists the user's labels by name, and the inbox as a folder. Same sentences.
A10 `mail_boxes` and `mail_labels` have `outside` false and `mail_search` and `mail_read` true, as the tools table says;
    the errand brief said every tool is `outside` true, which the table contradicts (design gap, reported).
A11 `mail_boxes` marks a mailbox as `shared` or kept and as `syncing`: keys `shared` and `syncing`. Rests on "the mailboxes
    this turn may use: address, shared or kept, still syncing".
A12 With part 2 only personal connections exist, so the gate is `owner_alone` and the connection must be the speaker's own.
    Rests on "Personal connections only, so the gate is `owner_alone`".
A13 A tool is offered only when the connection was granted a Gmail scope (the `gmail.readonly` segment). A connection that
    `needs` a reconnect still offers the tools, so she can say so. Rests on "A tool needing a Google scope the connection
    was not granted is not offered" and "her tools over it answer `needs_reconnect`".
A14 With no mail connection `for_turn` offers no mail tools, and a call to one answers `is_error` and reaches no Gmail
    (the Null Object). Rests on "Mail ... with a Null Object default" in the systems rule and `CodeHostTools`.
A15 The adapter fetches message headers with one `messages.get` per id (`format=metadata` or `full`); the fake does not
    serve Gmail's `/batch` endpoint. Rests on nothing but Gmail's reference; the design is silent.
A16 A read's page fits `READABLE_CHARS` (`channels.turn_tools`), as `git_read_file`'s does. Rests on "paged with `start` and
    `next_start` as `git_read_file` is".
A17 The search's cap is whatever the build sets in `mail.json`; no test names its value. A search with many more matches
    than any sane cap answers fewer, marks `cut` and gives `next_page`; paging to the end gives every match once.
    Rests on "capped and marked `cut`" and "page sizes and caps" being data.
A18 `mail.call` logs carry `call`, `status`, `count` and `duration_ms`. Rests on "`mail.call` (connection id, mailbox's
    resource id, call, status, count, duration_ms)".
A19 A tainting read is the turn's `Outside` seeing a result whose spec has `outside` true: the turn is tainted by the tool's
    name. Rests on "Reading mail taints the turn, so every change after it is held for `carry_out`".
A20 `ashley.mail.mailbox` holds `Mailbox` and `MailFailed(reason)`; `ashley.mail.model` the records; `ashley.mail.gmail`
    `GmailMailbox`; `ashley.tools.mail` `MailTools`. Rests on the `planned:` names.
"""

import base64
import json
from collections.abc import Awaitable, Callable, Generator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

import psycopg
import pytest
from ashley import services
from ashley.channels import standing
from ashley.channels.model import Audience, Inbound
from ashley.channels.steps import NO_STEPS
from ashley.channels.turn_tools import for_turn
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Grant, Listed
from ashley.connections.oauth_connections import OAuthConnections
from ashley.connections.resources import ConnectionResources
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.main import create_app
from ashley.settings import Settings
from ashley.tools.composite import CompositeTools
from ashley.tools.outside import Outside
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import household, person, scalar
from fastapi.testclient import TestClient
from receipts_shown import held_text
from mail_gmail_blind_fake_support import CLIENT_ID, CLIENT_SECRET, FakeGmail, Msg

T = TypeVar("T")
PUBLIC = "https://ashley.test"
APP_KEY = base64.b64encode(bytes(range(32))).decode()
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
BASE_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.email")
BOXES, LABELS, SEARCH, READ = "mail_boxes", "mail_labels", "mail_search", "mail_read"
MAIL_TOOLS = (BOXES, LABELS, SEARCH, READ)
CHANGE = "house_do"
SEED_ACCESS, SEED_REFRESH = "at-seed-0001-ACCESSTOKEN", "rt-seed-0001-REFRESHTOKEN"


def day(month: int, d: int, hour: int = 12) -> datetime:
    return datetime(2026, month, d, hour, tzinfo=UTC)


def message(ident: str, when: datetime, subject: str = "Hello", sender: str = "Alice <alice@school.test>",
            **fields: Any) -> Msg:
    return Msg(ident, subject, sender, fields.pop("to", "alana@gmail.test"), when, **fields)


class Changes(Tools):
    """A change tool beside the mail tools, so a test sees whether a change after a read runs or is held."""

    def __init__(self) -> None:
        self.ran: list[ToolCall] = []

    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec(CHANGE, "change something", {"type": "object", "properties": {}}, False, False),),
                         None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return ToolResult(call.id, "done", False)


class Turn:
    """One turn's tools (`for_turn`), driven from sync tests on the app's own event loop."""

    def __init__(self, world: "World", tools: Tools) -> None:
        self.world, self.tools, self.serial = world, tools, 0

    def specs(self) -> dict[str, ToolSpec]:
        return {s.name: s for s in self.world.run(self.tools.catalogue).specs}

    def names(self) -> set[str]:
        return set(self.specs())

    def call(self, name: str, **arguments: object) -> ToolResult:
        return self.send(name, arguments)

    def send(self, name: str, arguments: Mapping[str, object]) -> ToolResult:
        return self.world.run(lambda: self.acall(name, **arguments))

    async def acall(self, name: str, **arguments: object) -> ToolResult:
        """The call on the running loop, for a test that runs two turns at once."""
        self.serial += 1
        return await self.tools.call(ToolCall(f"c{self.serial}", name, dict(arguments)))


@dataclass
class World:
    client: TestClient
    url: str
    fake: FakeGmail
    hid: int
    other_hid: int
    alana: int
    sam: int
    kim: int
    conversation: int
    serial: int = 0

    def run(self, call: Callable[[], Awaitable[T]]) -> T:
        portal = self.client.portal
        assert portal is not None
        return portal.call(call)

    def connect(self, who: str = "alana", scopes: tuple[str, ...] = (*BASE_SCOPES, GMAIL_SCOPE), expires_in_s: int = 86_400,
                access: str = SEED_ACCESS, refresh: str = SEED_REFRESH) -> int:
        """A Google connection of `who`, made as part 1 makes one and stored with its mailbox's address as the connect
        flow stores it (`ConnectionResources.listed`); the fake accepts its tokens. Returns its id."""
        self.fake.accept(access, refresh)
        person_id, hid = getattr(self, who), self.other_hid if who == "kim" else self.hid

        async def add() -> int:
            kind = services.get(ConnectionKinds).get("google")
            assert kind is not None and kind.fixed_address is not None
            made = await services.get(OAuthConnections).add_oauth(
                hid, "google", "", kind.fixed_address, Grant(access, refresh, expires_in_s, scopes), person_id)
            await services.get(ConnectionResources).listed(made.id, hid, [Listed(self.fake.address, "mailbox", self.fake.address)])
            return made.id

        return self.run(add)

    def mark_reconnect(self, connection_id: int) -> None:
        async def mark() -> None:
            state = await services.get(OAuthConnections).state(connection_id, self.hid, self.alana)
            assert state is not None
            assert await services.get(OAuthConnections).needs_reconnect(connection_id, state.version)

        self.run(mark)

    def needs(self, connection_id: int) -> str | None:
        found = scalar(self.url, "SELECT needs FROM connections WHERE id = %s", (connection_id,))
        return None if found is None else str(found)

    def inbound(self, who: str = "alana", audience: Audience = "owner", shared: bool = False,
                device_id: int | None = None, speaker: bool = True, **fields: Any) -> Inbound:
        person_id = getattr(self, who)
        hid = self.other_hid if who == "kim" else self.hid
        return Inbound(hid, f"web:{person_id}", "what is in my mail", "chat", "text", audience,
                       person_id if speaker else None, shared, None, "web", device_id=device_id, **fields)

    def turn(self, who: str = "alana", **fields: Any) -> Turn:
        inbound = self.inbound(who, **fields)

        async def build() -> Tools:
            return for_turn(inbound)

        return Turn(self, self.run(build))

    def guarded(self, who: str = "alana", taint: str | None = None) -> "Guarded":
        """A turn whose tools are wrapped in `Outside` beside one change tool, as a person's turn is."""
        inbound = self.inbound(who, taint=taint)
        changes = Changes()
        self.serial += 1
        turn_id = int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                             "visibility) VALUES (%s, %s, 'person', %s, 'yes', 'shared') RETURNING id",
                             (self.conversation, self.hid, self.alana)))

        async def build() -> Outside:
            both = CompositeTools({"turn": for_turn(inbound), "changes": changes})
            return Outside(both, standing.of(inbound), (self.conversation, turn_id), NO_STEPS, inbound.taint)

        outside = self.run(build)
        return Guarded(Turn(self, outside), outside, changes, self)


@dataclass
class Guarded:
    turn: Turn
    outside: Outside
    changes: Changes
    world: World

    def pending(self) -> str | None:
        return held_text(self.world.run(self.outside.receipts)) or None


def build_world(url: str, fake: FakeGmail, client: TestClient) -> World:
    home, other = household(url, "home"), household(url, "other")
    alana, sam, kim = person(url, home, "Alana"), person(url, home, "Sam"), person(url, other, "Kim")
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                     "VALUES (%s, %s, %s)", (conversation, home, alana))
    return World(client, url, fake, home, other, alana, sam, kim, conversation)


def app_client(url: str, fake: FakeGmail, monkeypatch: pytest.MonkeyPatch, keyed: bool = True) -> Generator[TestClient]:
    """The real app on the database, every HTTP request of the process going to `fake`."""
    fake.install(monkeypatch)
    keys = {"connections_key": APP_KEY} if keyed else {}
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, google_oauth_client_id=CLIENT_ID,
                              google_oauth_client_secret=CLIENT_SECRET, **keys))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c


# --- reading results -----------------------------------------------------------------------------------------------


def data(result: ToolResult) -> Any:
    assert not result.is_error, result.content
    return json.loads(result.content)


def failed(result: ToolResult, reason: str) -> None:
    assert result.is_error, f"expected the failure {reason}, got: {result.content[:200]}"
    assert reason in result.content, result.content


def dig(found: Any, key: str) -> Any:
    """The first value stored under `key` anywhere in parsed JSON, depth first; a missing key is `ABSENT`."""
    loose: Any = found
    children: list[Any]
    if isinstance(found, dict):
        mapping = dict[str, Any](loose)
        if key in mapping:
            return mapping[key]
        children = list(mapping.values())
    elif isinstance(found, list):
        children = list[Any](loose)
    else:
        return ABSENT
    for child in children:
        got = dig(child, key)
        if got != ABSENT:
            return got
    return ABSENT


ABSENT = "<absent>"


def page_text(found: Any) -> Any:
    """The message text a read page carries, under `body` or `text`; `ABSENT` when under neither."""
    got = dig(found, "body")
    return dig(found, "text") if got == ABSENT else got


def headers_of(found: Any) -> list[dict[str, Any]]:
    """The list of header records in a search answer: the first list of objects that each carry `id` and `subject`."""
    loose: Any = found
    children: list[Any]
    if isinstance(found, list):
        items = list[Any](loose)
        if items and all(isinstance(x, dict) and "id" in x and "subject" in x for x in items):
            return [dict[str, Any](x) for x in items]
        children = items
    elif isinstance(found, dict):
        children = list(dict[str, Any](loose).values())
    else:
        return []
    for child in children:
        got = headers_of(child)
        if got:
            return got
    return []


def as_records(value: Any) -> list[dict[str, Any]]:
    """A parsed JSON list of objects."""
    loose: Any = value
    return [dict[str, Any](x) for x in list[Any](loose)]


def ids_of(found: Any) -> list[str]:
    return [str(h["id"]) for h in headers_of(found)]


def attachment_count(header: Mapping[str, Any]) -> int | None:
    for key in ("attachments", "attachment_count", "attachments_count"):
        if isinstance(header.get(key), int) and not isinstance(header.get(key), bool):
            return int(header[key])
    return None


def search(turn: Turn, **query: object) -> Any:
    return data(turn.send(SEARCH, {"mailbox": ADDRESS, **query}))


ADDRESS = "alana@gmail.test"


def whole_text(*results: ToolResult) -> str:
    return "\n".join(r.content for r in results)
