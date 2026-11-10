"""Blind contract tests for Proton's mailbox (decisions.md, "Her mail is a port with two adapters, and Proton's runs as a
leased Bridge", build parts 5 and 6, Proton's side): the real app on a real database, a fake Proton Mail Bridge on
localhost sockets (`mail_proton_blind_bridge_support`: IMAP and SMTP over the same accounts), and the turn's tools as
`ashley.channels.turn_tools.for_turn` offers them, wrapped in `ashley.tools.outside.Outside` as a person's turn is. The
tests never name the adapter; the one place that does is `wire_adapter` below, which a reconciler rewires.

ASSUMPTIONS (the same list, with the design sentence under each, is in `~/scratch/ashley/mail/proton-blind/assumptions.txt`):

G1  The adapter is `ashley.mail.imap.ImapMailbox`, built as `ImapMailbox(hosts, config, imap_port, smtp_port)` behind `RoutedMailbox`, signing in over STARTTLS with the certificate pinned by the fingerprint in the record's heartbeat: the
    Bridge Service addresses (hosts only, no scheme; the design's `MAIL_BRIDGE_KEEPER_URL` list serves IMAP and SMTP too),
    the two ports (the design's 2143 and 2025, given here because a test cannot bind them), and the `MailConfig`. Rests
    on "`planned:ashley.mail.imap.ImapMailbox` (SMTP for sending)" and "The same list serves part 5's IMAP and SMTP".
G2  The Mailbox service is registered as that adapter alone, so a Proton connection is served by it; where the build routes
    between Gmail's adapter and this one by the connection's kind, `wire_adapter` registers the router. Rests on nothing:
    the design has one `Mailbox` and two adapters.
G3  The adapter signs in with the Bridge account's address as the IMAP and SMTP user and the connection's sealed secret as
    the password (the Bridge password the kind stores), over the transport `FakeBridge.tls` says: 'none' (plain), or
    'implicit' or 'starttls' with a self-signed certificate whose fingerprint `FakeBridge.cert.fingerprint` is, which
    `wire_adapter` hands the record's heartbeat if the build pins it. Rests on "the connection is stored with the
    account's Bridge password as its sealed secret" and "The app pins Bridge's TLS certificate by the fingerprint".
G4  The Proton kind's connection has no Gmail scope, so `Mailbox.can_read` and `can_change` are true for it (the adapter
    is the Proton one). Rests on the kind having `ports={"mail"}` and no scopes.
G5  A mailbox is one Bridge account in split address mode, named by its address, and its resource is stored when the
    connection is (the suite stores it, as the connect flow will). Rests on "a Proton account in split address mode is
    one per address".
G6  An account's `syncing` (record: connected and `synced_epoch` not the current epoch) makes `mail_labels`, `mail_search`
    and `mail_read` answer `is_error` with `syncing` in the text and no `messages` or `labels` key, and `mail_boxes` list
    the mailbox with `syncing` true. A label change on a syncing mailbox is refused and changes nothing. A draft or a send
    on one is not asserted. Rests on "answers every read `syncing`" and "never an empty mailbox".
G7  An account Bridge signed out (record state `signed_out`, its connection's `needs` `login`) answers `needs_reconnect`,
    as every connection that needs a login does. Rests on "her tools over it answer `needs_reconnect` rather than empty
    results" and "(`login` (a Proton account Bridge signed out)".
G8  A login Bridge refuses (IMAP `NO [AUTHENTICATIONFAILED]` or SMTP 535) answers `needs_reconnect` or `refused`, an
    error that is neither `syncing`, `unreachable` nor an empty result; nothing is sent. A server that does not answer or
    does not speak IMAP answers `unreachable`. Rests on "IMAP login failure surfaces as a clear error" and the reasons'
    meanings in `ashley.mail.model`.
G9  A message's id is its `Message-ID` header (the id contains the header's address part); one with none gets a hash of
    date, sender and subject, stable across a resync. Rests on "for Proton the `Message-ID` header (a hash of date,
    sender and subject for a message with none)". A message in several mailboxes (a folder and its labels) is one message.
G10 A search with no folder reaches every message in the mailbox that is in a folder or label, once, Spam and Trash
    apart. Folders as `mail_labels` names them are lower case (`inbox`, `sent`, `drafts`, `archive`, `spam`, `trash`);
    labels are the names under `Labels/` with that prefix dropped; `All Mail` and `Folders/...` are neither. Rests on
    `Label`'s "named in lower case" and "the household's own labels".
G11 Reading a message, and searching, leave its unread state as it was. Rests on parity with Gmail, whose reads never
    modify, and on a read being a read.
G12 A draft is an IMAP APPEND of the whole message to `Drafts` with `\\Draft`, carrying From (the address), To, Cc,
    Subject, Date, Message-ID, and for a reply In-Reply-To (and References) set to the original's Message-ID; it is not sent.
    The id it gives is the Message-ID of what was appended. Rests on "draft = APPEND to Drafts".
G13 A send goes over SMTP submission once, MAIL FROM the mailbox's address, RCPT TO each of `to` and `cc` and no other
    (never a Bcc), the message carrying the same headers as a draft; the adapter does not save a copy in Sent (Bridge's
    server does). The id it gives is the Message-ID of the message sent. A failed or dropped send is `unreachable` or
    `refused` and is never retried: one DATA attempt. Rests on "send goes over SMTP" and "A send is posted once and never
    retried".
G14 A label is a copy of the message in `Labels/<name>`: adding copies it there, removing deletes that copy; the message's
    folder copy and its other labels stay. A folder move (`inbox`, `archive`, `spam`, `trash`) takes the message out of
    the folder it was in and puts it in the new one, leaving its labels; `unread` sets or clears `\\Seen`. A name that is no
    label of the mailbox, or an id of no message, refuses the whole call, nothing changed and nothing created
    (no CREATE, DELETE or RENAME command). Rests on "label change = folder copy/move under Labels/".
G15 A label call whose targets' sender and subject do not begin with what the id's message has is `refused` whole; an id of
    no message is `not_found`. Rests on `Mailbox.change`'s docstring.
G16 `mail.call` is logged for each call with `call`, `status`, `count`, `duration_ms`; no log record, at any level, carries
    an address, subject, body, label, query, password or server reply text. Rests on the Logs section.
"""

import base64
import hashlib
import json
from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass
from typing import Any, TypeVar

import psycopg
from ashley import services
from ashley.channels import standing
from ashley.channels.model import Audience, Inbound
from ashley.channels.steps import NO_STEPS
from ashley.channels.turn_tools import for_turn
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Listed
from ashley.connections.resources import ConnectionResources
from ashley.connections.sealing import VERSION, Sealer, key_from
from ashley.db.database import Database
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.mail import config as mail_config
from ashley.mail.imap import ImapMailbox
from ashley.mail.mailbox import Mailbox
from ashley.mail.proton_bridge import ProtonBridge, Sync
from ashley.mail.proton_bridge_postgres import PostgresProtonBridge
from ashley.mail.proton_kind import ADDRESS, PROTON
from ashley.mail.routed import RoutedMailbox
from ashley.main import create_app
from ashley.settings import Settings
from ashley.tools.outside import Outside
from ashley.tools.tools import Tools
from ashley.wiring import CONNECTION_KINDS
from contract.conversations_support import household, person, scalar
from fastapi.testclient import TestClient
from receipts_shown import held_text
from mail_proton_blind_bridge_support import FakeBridge
from mail_proton_blind_store_support import Account as BridgeAccount, compose, when

T = TypeVar("T")
PUBLIC = "https://ashley.test"
APP_KEY = base64.b64encode(bytes(range(32))).decode()
PASSWORD = "bridge-password"
BOXES, LABELS, SEARCH, READ = "mail_boxes", "mail_labels", "mail_search", "mail_read"
DRAFT, LABEL, SEND = "mail_draft", "mail_label", "mail_send"
ALANA_ADDRESS = "alana@proton.test"
ROW_KEYS = {"id", "from", "to", "subject", "date", "snippet", "labels", "folder", "unread", "attachments"}
CONFIG = mail_config.load()


def wire_adapter(bridge: FakeBridge) -> None:
    """The one place the adapter is named and pointed at the fake Bridge (G1, G2, G3): the router as the app wires it,
    Proton's adapter alone behind it, reaching the fake on its two ports."""
    imap = ImapMailbox(("127.0.0.1",), CONFIG, bridge.imap_port, bridge.smtp_port)
    services.register(Mailbox, RoutedMailbox({PROTON.name: imap}))


def register_services(settings: Settings) -> None:
    services.register(ConnectionKinds, ConnectionKinds((*CONNECTION_KINDS, PROTON)))
    services.register(ProtonBridge, PostgresProtonBridge(services.get(Database),
                                                         Sealer({VERSION: key_from(settings.connections_key)})))


def app_client(url: str, bridge: FakeBridge) -> Generator[TestClient]:
    settings = Settings(database_url=url, build_version="t", public_url=PUBLIC, connections_key=APP_KEY)
    with TestClient(create_app(settings), base_url=PUBLIC, follow_redirects=False) as c:
        register_services(settings)
        wire_adapter(bridge)
        yield c


@dataclass(frozen=True)
class Box:
    """A Proton mailbox of the household: its connection, address, Bridge user id and the fake's account."""

    connection_id: int
    address: str
    user_id: str
    account: BridgeAccount


class Turn:
    """One turn's tools, driven from sync tests on the app's own event loop."""

    def __init__(self, world: "World", tools: Tools) -> None:
        self.world, self.tools, self.serial = world, tools, 0

    def specs(self) -> dict[str, ToolSpec]:
        return {s.name: s for s in self.world.run(self.tools.catalogue).specs}

    def names(self) -> set[str]:
        """The mail tools offered; the turn's other tools are not this suite's."""
        return {n for n in self.specs() if n.startswith("mail_")}

    def call(self, name: str, **arguments: object) -> ToolResult:
        self.serial += 1
        call = ToolCall(f"c{self.serial}", name, dict(arguments))
        return self.world.run(lambda: self.tools.call(call))


class Guarded(Turn):
    """A turn wrapped in `Outside`: `tainted` and the pending block are the turn's own."""

    def __init__(self, world: "World", outside: Outside) -> None:
        super().__init__(world, outside)
        self.outside = outside

    def pending(self) -> str:
        return held_text(self.world.run(self.outside.receipts))

    @property
    def tainted(self) -> str | None:
        return self.outside.tainted

    def carry_out(self) -> ToolResult:
        return self.call("carry_out")


@dataclass
class World:
    client: TestClient
    url: str
    bridge: FakeBridge
    hid: int
    alana: int
    sam: int
    conversation: int
    epoch: int = 0

    def run(self, call: Callable[[], Awaitable[T]]) -> T:
        portal = self.client.portal
        assert portal is not None
        return portal.call(call)

    def record(self) -> ProtonBridge:
        return services.get(ProtonBridge)

    def start_epoch(self) -> int:
        """A new Bridge epoch, as a holder raises one; every account not synced in it is syncing."""
        async def raised() -> int:
            record = self.record()
            got = await record.raise_epoch((await record.holder()).epoch, "site-a", hashlib.sha256(b"t").digest())
            assert got is not None
            assert await record.heartbeat(got, self.bridge.cert.fingerprint)
            return got

        self.epoch = self.run(raised)
        return self.epoch

    def box(self, address: str = ALANA_ADDRESS, *, synced: bool = True, who: str = "alana", label: str = "",
            password: str = PASSWORD) -> Box:
        """A Proton connection of `who` for `address`, its account in the record (synced in the current epoch unless
        not `synced`), its mailbox stored as a resource, and the fake Bridge's account of that address."""
        epoch = self.epoch or self.start_epoch()
        owner = getattr(self, who)
        user_id = f"user-{address}"

        async def add() -> int:
            made = await services.get(Connections).add(self.hid, "proton", label or address, ADDRESS, password, owner)
            await self.record().add_account(made.id, user_id, (address,), epoch if synced else 0)
            await services.get(ConnectionResources).listed(made.id, self.hid, [Listed(address, "mailbox", address)])
            return made.id

        return Box(self.run(add), address, user_id, self.bridge.account(address, PASSWORD))

    def sync(self, box: Box, event: Sync = "finished", progress: float | None = None) -> None:
        async def go() -> None:
            assert await self.record().sync(self.epoch, box.user_id, event, progress) is not None

        self.run(go)

    def sign_out(self, box: Box) -> None:
        async def go() -> None:
            assert await self.record().set_state(self.epoch, box.user_id, "signed_out") is not None

        self.run(go)

    def share(self, box: Box) -> None:
        async def go() -> None:
            assert await services.get(ConnectionResources).share(box.connection_id, self.hid, self.alana, box.address, True)

        self.run(go)

    def inbound(self, who: str = "alana", audience: Audience = "owner", shared: bool = False, speaker: bool = True,
                **fields: Any) -> Inbound:
        person_id = getattr(self, who)
        return Inbound(self.hid, f"web:{person_id}", "send it", "chat", "text", audience,
                       person_id if speaker else None, shared, None, "web", **fields)

    def turn(self, who: str = "alana", **fields: Any) -> Turn:
        inbound = self.inbound(who, **fields)

        async def build() -> Tools:
            return for_turn(inbound)

        return Turn(self, self.run(build))

    def guarded(self, who: str = "alana", **fields: Any) -> Guarded:
        """A person's turn: the tools wrapped in `Outside`. Each call makes a later turn of the same conversation."""
        inbound = self.inbound(who, **fields)
        turn_id = int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                             "visibility) VALUES (%s, %s, 'person', %s, 'yes', 'shared') RETURNING id",
                             (self.conversation, self.hid, getattr(self, who))))

        async def build() -> Outside:
            return Outside(for_turn(inbound), standing.of(inbound), (self.conversation, turn_id), NO_STEPS, inbound.taint)

        return Guarded(self, self.run(build))


def build_world(url: str, bridge: FakeBridge, client: TestClient) -> World:
    home = household(url, "home")
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    with psycopg.connect(url, autocommit=True) as conn:
        for who in (alana, sam):
            conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                         "VALUES (%s, %s, %s)", (conversation, home, who))
    return World(client, url, bridge, home, alana, sam, conversation)


def data(result: ToolResult) -> Any:
    assert not result.is_error, result.content
    return json.loads(result.content)


def failed(result: ToolResult, *reasons: str) -> None:
    """An error whose text names one of `reasons` (any error when none is given)."""
    assert result.is_error, f"expected a failure, got: {result.content[:200]}"
    assert not reasons or any(r in result.content for r in reasons), result.content


def rows(result: ToolResult) -> list[dict[str, Any]]:
    return list(data(result)["messages"])


def by_subject(world: World, subject: str, address: str = ALANA_ADDRESS) -> dict[str, Any]:
    """The one listed row whose subject is `subject`, as `mail_search` gives it."""
    found = [r for r in rows(world.turn().call(SEARCH, mailbox=address, text=subject.split()[0])) if r["subject"] == subject]
    assert len(found) == 1, found
    return found[0]


def target(row: dict[str, Any]) -> dict[str, str]:
    """A label call's `messages` entry for a listed row."""
    return {"id": row["id"], "from": row["from"], "subject": row["subject"]}


M1, M2, M3, M4, M5, M6 = (f"<m{n}@{host}>" for n, host in
                          ((1, "school.test"), (2, "shop.test"), (3, "cafe.test"), (4, "proton.test"), (5, "spam.test"),
                           (6, "shop.test")))
SUBJECTS = {M1: "Trip money", M2: "Invoice 4412", M3: "Lunch menu", M4: "Re: Trip money", M5: "Win a prize",
            M6: "Old receipt"}


def stock(box: Box, to: str = "") -> None:
    """Six messages in the mailbox and its labels `School` and `Receipts`: M1 (unread, labelled School), M2 (a pdf), M3
    (HTML only) in the inbox, M4 in Sent, M5 in Spam, M6 archived and labelled Receipts."""
    me = to or box.address
    mine = box.account
    mine.make("Labels/School")
    mine.make("Labels/Receipts")
    mine.seed("INBOX", compose(SUBJECTS[M1], "Pat <pat@school.test>", me, when(3, 4), "bring ten dollars", message_id=M1),
              labels=("School",), unread=True, when=when(3, 4))
    mine.seed("INBOX", compose(SUBJECTS[M2], "Bob Shop <bob@shop.test>", me, when(3, 3), "Pay by Friday", message_id=M2,
                               attachments=(("invoice.pdf", "application/pdf", b"%PDF-1.4 x"),)), when=when(3, 3))
    mine.seed("INBOX", compose(SUBJECTS[M3], "Cy <cy@cafe.test>", me, when(3, 2), "", message_id=M3,
                               html="<html><body><p>Soup <b>today</b></p><script>x()</script></body></html>"),
              when=when(3, 2))
    mine.seed("Sent", compose(SUBJECTS[M4], me, "pat@school.test", when(3, 5), "ok, sending ten", message_id=M4),
              when=when(3, 5))
    mine.seed("Spam", compose(SUBJECTS[M5], "Win <win@spam.test>", me, when(3, 6), "claim now", message_id=M5),
             when=when(3, 6))
    mine.seed("Archive", compose(SUBJECTS[M6], "Bob Shop <bob@shop.test>", me, when(2, 20), "receipt for the lamp",
                                 message_id=M6), labels=("Receipts",), when=when(2, 20))


def snapshot(box: Box) -> dict[str, object]:
    """Where every message is and its read state, as the fake Bridge holds it: what a refused call must not change."""
    held = {mid: (box.account.where(mid), box.account.unread(mid)) for mid in SUBJECTS}
    return {"held": held, "folders": sorted(box.account.folders), "commands": list(box.account.commands)}
