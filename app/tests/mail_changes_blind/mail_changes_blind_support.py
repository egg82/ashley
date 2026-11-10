"""Blind contract tests for changes to mail (decisions.md, "Her mail is a port with two adapters, and Proton's runs as a
leased Bridge", build part 6): the real app on a real database, a fake Gmail at its HTTP boundary
(`mail_changes_blind_fake_support`), and the turn's tools as `ashley.channels.turn_tools.for_turn` offers them, wrapped in
`ashley.tools.outside.Outside` as a person's turn is. Everything the design does not name is guessed once, in ASSUMPTIONS
below; a test never guesses on its own. The same list, with the design sentence under each, is in
`~/scratch/ashley/mail/mail-changes-blind/assumptions.txt`.

ASSUMPTIONS (each with the design sentence it rests on):

C1  The tools are `mail_draft`, `mail_label` and `mail_send`, offered by `for_turn` beside the read tools. Rests on the
    tools table.
C2  A mailbox is named by its address in the argument `mailbox`, as the read tools do. Rests on "name a mailbox by its
    address".
C3  `mail_draft` and `mail_send` take `to` and `cc` as lists of address strings, `subject` and `body` as strings, and
    `reply_to`, the id of the message answered (optional). Rests on "`Draft` (to, cc, subject, body, the message it replies
    to)".
C4  `mail_label` takes `messages`, a list of objects `{id, from, subject}` (the sender and subject as `mail_search` shows
    them), `add` and `remove` (lists of the household's label names as `mail_labels` lists them), `folder`
    (a folder name as `mail_labels` lists them) and `unread` (boolean). Rests on "`MailChange` (labels to add and remove, a
    folder to move to, read or unread)" and "A label's arguments carry each message's sender and subject beside its id".
C5  A label call whose `from` or `subject` does not match the message of its `id`, or whose id is none of the mailbox's, is
    refused whole: `is_error`, and no message of the call changes (all or nothing). Rests on "the adapter refuses a call
    whose sender or subject does not match the id".
C6  A label name that is none of the household's (unknown, or a Gmail system label such as `TRASH` or `UNREAD`), a folder
    that is none of `mail_labels`' folders, or an argument of the wrong shape is refused, the mailbox is left as it was and
    no label is created. Rests on "labels add/remove as asked and nothing else" (a MailChange has labels, a folder, read).
C7  The change scope is Gmail's `gmail.modify`, which the Google kind asks for in place of `gmail.readonly`. Rests on
    "Gmail's scope raised to `gmail.modify` (a reconnect, which the room asks for)".
C8  A connection that was granted only `gmail.readonly` is offered the change tools and answers `needs_reconnect` to
    each; nothing is sent, drafted or changed. The design's "not offered" is for a tool whose scope no connection could
    have, and the errand brief's "answers needs_reconnect" is the behaviour pinned here.
C9  A success is JSON text with no required key; a failure is `is_error` with the reason's name (`needs_reconnect`,
    `unreachable`, `refused`, `not_found`) in the text, as part 2's A4. A change that cannot be made for a bad argument
    names no reason this suite looks for.
C10 Gmail is written as its reference says: a send is `messages.send` with the whole RFC 822 message base64url in `raw`
    (plus `threadId` for a reply), a draft is `drafts.create` with `{"message": {"raw"}}`, a label or move is
    `messages.modify` or `batchModify`, and a move to the trash is a modify adding `TRASH` or `messages.trash`. The body
    is text/plain, or HTML read back as text. The design is silent on the calls.
C11 A reply sets `In-Reply-To` to the original's `Message-ID` and `threadId` to its thread. Rests on `Draft` carrying "the
    message it replies to" and Gmail's threading rule.
C12 `max_body_chars` and `max_change_ids` are keys of `app/ashley/mail/mail.json`. A body of more than `max_body_chars`
    characters, or a label call over `max_change_ids` ids, is refused and nothing is stored or changed. A held send whose
    body is exactly `max_body_chars` long (letters), with a short recipient and subject, fits `max_argument_chars` and is
    held. Rests on "`max_body_chars` for a draft must fit `max_argument_chars` in `app/ashley/tools/outside.json`" and
    "at most `max_change_ids`".
C13 `mail.call` is logged once or more for each change, with the keys `call`, `status`, `count`, `duration_ms`, and the
    failure's reason as `status`. Rests on "`mail.call` (connection id, mailbox's resource id, call, status, count,
    duration_ms)".
C14 The pending block shows the arguments of a held call in full (code writes it from the arguments), so it carries a
    send's recipients, subject and body and a label's ids, senders, subjects and label names. Rests on "the pending block
    shows each held call's arguments in full".
C15 A recipient, subject or reply id carrying a line break cannot add a header: the call is refused, or the message made
    has no header the call did not name. Rests on nothing but safe MIME; the design is silent.
C16 A send with no recipient is refused and sends nothing. Rests on a `Draft` being sent "from the mailbox".
C17 `ashley.google.kind.GOOGLE.connect.scopes` lists the change scope; `OAuth.missing` of a readonly grant names it. Rests
    on C7 and "the room says what is missing".
C18 An id the mailbox does not have is `not_found` in a reply and in a label call. Rests on part 2's `not_found`.
C19 Moving to the trash is `folder: "trash"`; back to the inbox `folder: "inbox"`; `unread` true or false adds or removes
    Gmail's UNREAD. Rests on "Moving to the trash is offered" and `Label`'s folder names ("inbox, sent, drafts, spam,
    trash, in lower case").
C20 Deleting forever is not offered: no tool or argument does it. Rests on "deleting forever is not".
"""

import base64
import json
from collections.abc import Awaitable, Callable, Generator, Mapping
from dataclasses import dataclass
from datetime import datetime
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
from ashley.tools.outside import Outside
from ashley.tools.tools import Tools
from contract.conversations_support import household, person, scalar
from fastapi.testclient import TestClient
from receipts_shown import held_text
from mail_changes_blind_fake_support import FakeGmail, Msg, moment

T = TypeVar("T")
PUBLIC = "https://ashley.test"
APP_KEY = base64.b64encode(bytes(range(32))).decode()
READONLY = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY = "https://www.googleapis.com/auth/gmail.modify"
BASE_SCOPES = ("openid", "https://www.googleapis.com/auth/userinfo.email")
DRAFT, LABEL, SEND = "mail_draft", "mail_label", "mail_send"
CHANGES = (DRAFT, LABEL, SEND)
SEARCH, READ = "mail_search", "mail_read"
ADDRESS = "alana@gmail.test"
SEED_ACCESS, SEED_REFRESH = "at-seed-0001-ACCESSTOKEN", "rt-seed-0001-REFRESHTOKEN"


def day(month: int, d: int, hour: int = 12) -> datetime:
    return moment(2026, month, d, hour)


def message(ident: str, when: datetime, subject: str = "Hello", sender: str = "Alice <alice@school.test>",
            **fields: Any) -> Msg:
    return Msg(ident, subject, sender, fields.pop("to", ADDRESS), when, **fields)


def stock(world: "World") -> None:
    """m1 (unread, Receipts), m2 and m3 in the inbox, m4 in the trash."""
    world.fake.add(message("m1", day(3, 4), "Hello", text="Please forward the key", labels=["INBOX", "UNREAD", "Label_13"]),
                   message("m2", day(3, 3), "Invoice", sender="Bob <bob@shop.test>", text="Pay by Friday"),
                   message("m3", day(3, 2), "Lunch", sender="Cy <cy@cafe.test>", text="Soup today"),
                   message("m4", day(3, 1), "Old", text="gone", labels=["TRASH"]))


def send_args(**over: object) -> dict[str, object]:
    base: dict[str, object] = {"mailbox": ADDRESS, "to": ["dana@club.test"], "subject": "Saturday",
                               "body": "See you at nine."}
    return {**base, **over}


def entry(ident: str, sender: str = "Alice <alice@school.test>", subject: str = "Hello") -> dict[str, str]:
    return {"id": ident, "from": sender, "subject": subject}


def label_args(*messages: dict[str, str], **over: object) -> dict[str, object]:
    """The build names the label lists `add` and `remove`; tests spell them `add_labels` and `remove_labels`."""
    names = {"add_labels": "add", "remove_labels": "remove"}
    return {"mailbox": ADDRESS, "messages": list(messages), **{names.get(k, k): v for k, v in over.items()}}


M1, M2, M3 = entry("m1"), entry("m2", "Bob <bob@shop.test>", "Invoice"), entry("m3", "Cy <cy@cafe.test>", "Lunch")


class Turn:
    """One turn's tools, driven from sync tests on the app's own event loop."""

    def __init__(self, world: "World", tools: Tools) -> None:
        self.world, self.tools, self.serial = world, tools, 0

    def specs(self) -> dict[str, ToolSpec]:
        return {s.name: s for s in self.world.run(self.tools.catalogue).specs}

    def names(self) -> set[str]:
        return set(self.specs())

    def call(self, name: str, **arguments: object) -> ToolResult:
        return self.send(name, arguments)

    def send(self, name: str, arguments: Mapping[str, object]) -> ToolResult:
        self.serial += 1
        call = ToolCall(f"c{self.serial}", name, dict(arguments))
        return self.world.run(lambda: self.tools.call(call))


@dataclass
class Guarded(Turn):
    """A turn wrapped in `Outside`: `tainted` and the pending block are the turn's own."""

    outside: Outside | None = None

    def __init__(self, world: "World", outside: Outside) -> None:
        super().__init__(world, outside)
        self.outside = outside

    def pending(self) -> str:
        assert self.outside is not None
        return held_text(self.world.run(self.outside.receipts))

    @property
    def tainted(self) -> str | None:
        assert self.outside is not None
        return self.outside.tainted

    def carry_out(self) -> ToolResult:
        return self.call("carry_out")


@dataclass
class World:
    client: TestClient
    url: str
    fake: FakeGmail
    hid: int
    alana: int
    sam: int
    conversation: int
    connection: int = 0

    def run(self, call: Callable[[], Awaitable[T]]) -> T:
        portal = self.client.portal
        assert portal is not None
        return portal.call(call)

    def connect(self, who: str = "alana", scopes: tuple[str, ...] = (*BASE_SCOPES, MODIFY), expires_in_s: int = 86_400,
                access: str = SEED_ACCESS, refresh: str = SEED_REFRESH) -> int:
        """A Google connection of `who`, stored with its mailbox's address as the connect flow stores it. The fake lets
        its token write only when `scopes` hold the change scope. Returns its id."""
        self.fake.accept(access, refresh, any(s.endswith("gmail.modify") for s in scopes))
        person_id = getattr(self, who)

        async def add() -> int:
            kind = services.get(ConnectionKinds).get("google")
            assert kind is not None and kind.fixed_address is not None
            made = await services.get(OAuthConnections).add_oauth(
                self.hid, "google", "", kind.fixed_address, Grant(access, refresh, expires_in_s, scopes), person_id)
            await services.get(ConnectionResources).listed(made.id, self.hid, [Listed(self.fake.address, "mailbox", self.fake.address)])
            return made.id

        self.connection = self.run(add)
        return self.connection

    def share(self, connection_id: int) -> None:
        async def go() -> None:
            assert await services.get(ConnectionResources).share(connection_id, self.hid, self.alana, ADDRESS, True)

        self.run(go)

    def mark_reconnect(self, connection_id: int) -> None:
        async def mark() -> None:
            state = await services.get(OAuthConnections).state(connection_id, self.hid, self.alana)
            assert state is not None
            assert await services.get(OAuthConnections).needs_reconnect(connection_id, state.version)

        self.run(mark)

    def inbound(self, who: str = "alana", audience: Audience = "owner", shared: bool = False,
                device_id: int | None = None, speaker: bool = True, **fields: Any) -> Inbound:
        person_id = getattr(self, who)
        return Inbound(self.hid, f"web:{person_id}", "send it", "chat", "text", audience,
                       person_id if speaker else None, shared, None, "web", device_id=device_id, **fields)

    def turn(self, who: str = "alana", **fields: Any) -> Turn:
        inbound = self.inbound(who, **fields)

        async def build() -> Tools:
            return for_turn(inbound)

        return Turn(self, self.run(build))

    def guarded(self, who: str = "alana", taint: str | None = None, **fields: Any) -> Guarded:
        """A person's turn: the tools wrapped in `Outside`. Each call makes a later turn of the same conversation, so a
        second `guarded` is the person's next message."""
        inbound = self.inbound(who, taint=taint, **fields)
        turn_id = int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                             "visibility) VALUES (%s, %s, 'person', %s, 'yes', 'shared') RETURNING id",
                             (self.conversation, self.hid, getattr(self, who))))

        async def build() -> Outside:
            return Outside(for_turn(inbound), standing.of(inbound), (self.conversation, turn_id), NO_STEPS, inbound.taint)

        return Guarded(self, self.run(build))


def build_world(url: str, fake: FakeGmail, client: TestClient) -> World:
    home = household(url, "home")
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    with psycopg.connect(url, autocommit=True) as conn:
        for who in (alana, sam):
            conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                         "VALUES (%s, %s, %s)", (conversation, home, who))
    return World(client, url, fake, home, alana, sam, conversation)


def app_client(url: str, fake: FakeGmail, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    """The real app on the database, every HTTP request of the process going to `fake`."""
    fake.install(monkeypatch)
    app = create_app(Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY,
                              google_oauth_client_id="gcid-changes.test", google_oauth_client_secret="gsecret-changes"))
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        yield c


def data(result: ToolResult) -> Any:
    assert not result.is_error, result.content
    return json.loads(result.content)


def failed(result: ToolResult, reason: str | None = None) -> None:
    assert result.is_error, f"expected a failure, got: {result.content[:200]}"
    if reason is not None:
        assert reason in result.content, result.content


def labels_now(world: World) -> dict[str, list[str]]:
    """Every message's Gmail label ids, as the mailbox holds them."""
    return {m.id: sorted(m.labels) for m in world.fake.messages}


def untouched(world: World, before: dict[str, list[str]]) -> None:
    """Nothing was sent or drafted, no label of any message moved, and nothing forbidden was tried."""
    assert world.fake.sent == [] and world.fake.drafts == [] and world.fake.forbidden == []
    assert labels_now(world) == before
