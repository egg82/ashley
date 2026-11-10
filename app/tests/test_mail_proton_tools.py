"""Her mail tools over a Proton connection and a Google one at once (`ashley.wiring`'s router): the same four reads and
three changes answer for either, `mail_boxes` says a mailbox is syncing, no tool names a provider, and the Proton kind
lists one mailbox per address of its Bridge account."""

import asyncio
import json
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ResourcesUnavailable
from ashley.connections.model import Connection, Listed, Opened, Resource
from ashley.connections.resources import ConnectionResources, Usable, Use, permits
from ashley.inference.model import ToolCall, ToolResult
from ashley.mail.imap import ImapMailbox
from ashley.mail.mailbox import Mailbox
from ashley.mail.model import Account, MailFailed, MailQuery
from ashley.mail.proton_bridge import Account as BridgeAccount, NullProtonBridge, ProtonBridge
from ashley.mail.proton_kind import PROTON
from ashley.mail.routed import RoutedMailbox
from ashley.tools.mail import MailTools
from mail_gmail_support import EPOCH, FakeGmail, message, wire as wire_gmail
from mail_proton_support import ALANA, HOME, PASSWORD, USER, Bridge, FakeBridge, Record, mail, stocked, wire
from money_support import HeldConnections

SAM_ADDRESS = "sam@proton.test"


@dataclass
class OneMailbox(ConnectionResources):
    """Each held connection's mailbox, named by `addresses`, kept for its owner."""

    held: HeldConnections
    addresses: Mapping[int, Sequence[str]]

    def _boxes(self) -> list[tuple[Connection, Resource]]:
        return [(o.connection, Resource(a, "mailbox", a, False)) for o in self.held.held.values()
                for a in self.addresses[o.connection.id]]

    async def of_household(self, household_id: int, person_id: int | None = None) -> dict[int, tuple[Resource, ...]]:
        return {c.id: (r,) for c, r in self._boxes()}

    async def listed(self, connection_id: int, household_id: int, found: Sequence[Listed]) -> tuple[Resource, ...]:
        return ()

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str,
                    shared: bool) -> Resource | None:
        return None

    async def usable(self, use: Use, changing: bool, kind: str = "mailbox") -> tuple[Usable, ...]:
        return tuple(Usable(c, r) for c, r in self._boxes() if permits(use, changing, c, r, True))


@pytest.fixture(scope="module")
def fake() -> Generator[FakeBridge]:
    server = FakeBridge()
    yield server
    server.stop()


@pytest.fixture
def bridge(fake: FakeBridge) -> Bridge:
    state = stocked(fake)
    config = wire(fake)
    gmail = FakeGmail([message("g1", "Gmail one", 1_762_000_000_000)])
    wire_gmail(gmail)
    held = HeldConnections()
    held.connect(HOME, "bridge://proton", PASSWORD, "proton", ALANA)
    held.held[(HOME, "google2")] = Opened(Connection(2, HOME, "google", "https://www.googleapis.com", ALANA, EPOCH, EPOCH, ALANA,
                                                     "", None, ("https://www.googleapis.com/auth/gmail.modify",)), "r")
    services.register(Connections, held)
    services.register(ConnectionResources, OneMailbox(held, {1: [USER], 2: ["alana@gmail.test"]}))
    google = services.get(Mailbox)
    services.register(Mailbox, RoutedMailbox({"google": google,
                                              "proton": ImapMailbox(("127.0.0.1",), config, fake.imap_port, fake.smtp_port)}))
    state.add("INBOX", mail("Field trip", message_id="<trip@school.test>"), (), "07-Nov-2026 10:00:00 +0000")
    return state


async def listed(opened: Opened) -> tuple[Listed, ...]:
    assert PROTON.resources is not None
    return await PROTON.resources(opened)


def say(name: str, args: Mapping[str, object] | None = None) -> ToolResult:
    return asyncio.run(MailTools(Use(1, ALANA, True), 8000).call(ToolCall("c", name, args or {})))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def test_one_set_of_tools_lists_a_mailbox_of_each_provider(bridge: Bridge) -> None:
    rows = body(say("mail_boxes"))["mailboxes"]
    assert sorted((r["address"], r["syncing"]) for r in rows) == [("alana@gmail.test", False), (USER, False)]


def test_search_and_read_answer_for_proton_through_the_same_tools(bridge: Bridge) -> None:
    found = body(say("mail_search", {"mailbox": USER, "subject": "field"}))
    assert [m["subject"] for m in found["messages"]] == ["Field trip"] and found["messages"][0]["id"] == "trip@school.test"
    read = body(say("mail_read", {"mailbox": USER, "id": "trip@school.test"}))
    assert read["text"] == "hello there"
    assert [m["subject"] for m in body(say("mail_search", {"mailbox": "alana@gmail.test"}))["messages"]] == ["Gmail one"]


def test_labels_a_draft_and_a_change_work_for_proton_through_the_same_tools(bridge: Bridge) -> None:
    assert {"name": "School", "folder": False} in body(say("mail_labels", {"mailbox": USER}))["labels"]
    assert body(say("mail_draft", {"mailbox": USER, "to": ["sam@school.test"], "subject": "Hi", "body": "Hello"}))["draft"]
    assert len(bridge.folders["Drafts"]) == 1
    moved = say("mail_label", {"mailbox": USER, "messages": [{"id": "trip@school.test", "from": "Sam", "subject": "Field"}],
                               "folder": "archive"})
    assert body(moved)["changed"] == 1 and len(bridge.folders["Archive"]) == 1


def test_a_mailbox_still_syncing_is_listed_as_syncing_and_every_read_says_so(bridge: Bridge, fake: FakeBridge) -> None:
    services.register(ProtonBridge, Record((BridgeAccount(1, 1, "user-1", "connected", (USER,), 2, 3, 0.4),),
                                           fake.fingerprint))
    rows = {r["address"]: r for r in body(say("mail_boxes"))["mailboxes"]}
    assert rows[USER]["syncing"] is True and rows["alana@gmail.test"]["syncing"] is False
    result = say("mail_search", {"mailbox": USER})
    assert result.is_error and "syncing" in result.content and "still being filled in" in result.content


def test_the_proton_kind_lists_one_mailbox_per_address_of_its_bridge_account(bridge: Bridge, fake: FakeBridge) -> None:
    wire(fake, addresses=(USER, SAM_ADDRESS))
    opened = Opened(Connection(1, HOME, "proton", "bridge://proton", ALANA, EPOCH, EPOCH, ALANA), PASSWORD)
    got = asyncio.run(listed(opened))
    assert [(r.ref, r.kind, r.name) for r in got] == [(USER, "mailbox", USER), (SAM_ADDRESS, "mailbox", SAM_ADDRESS)]


def test_a_proton_connection_bridge_holds_no_account_for_lists_none(bridge: Bridge) -> None:
    services.register(ProtonBridge, Record((), None))
    opened = Opened(Connection(1, HOME, "proton", "bridge://proton", ALANA, EPOCH, EPOCH, ALANA), PASSWORD)
    with pytest.raises(ResourcesUnavailable):
        asyncio.run(listed(opened))
    services.register(ProtonBridge, NullProtonBridge())
    with pytest.raises(ResourcesUnavailable):
        asyncio.run(listed(opened))


def test_a_connection_of_a_kind_with_no_adapter_is_refused_not_answered_empty(bridge: Bridge) -> None:
    router = RoutedMailbox({"google": services.get(Mailbox)})
    with pytest.raises(MailFailed) as e:
        asyncio.run(router.search(Account(1, HOME, ALANA, "proton", USER), MailQuery()))
    assert e.value.reason == "refused"


def test_the_router_asks_the_adapter_of_the_connections_kind_and_a_google_connection_with_no_scopes_is_not_proton(
        bridge: Bridge) -> None:
    mailbox = services.get(Mailbox)
    assert mailbox.can_read("proton", ()) and mailbox.can_change("proton", ())
    assert mailbox.can_read("google", ("https://www.googleapis.com/auth/gmail.modify",))
    assert not mailbox.can_read("google", ("openid", "email"))
    assert not mailbox.can_read("google", ()) and not mailbox.can_change("google", ())
    assert not mailbox.can_read("other", ())
