"""`mail_boxes` lists a mailbox the turn may see but her mail tools cannot use now, each with an `unavailable` reason
field, so a connection that cannot be read never just vanishes from the listing."""

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.model import Connection, Listed, Needs, Opened, Resource, ResourceKind
from ashley.connections.resources import ConnectionResources, Usable, Use, permits
from ashley.inference.model import ToolCall
from ashley.mail.mailbox import Mailbox
from ashley.mail.routed import RoutedMailbox
from ashley.tools.mail import MailTools
from mail_gmail_support import ADDRESS, ALANA, EPOCH, HOME, FakeGmail, message, wire
from money_support import HeldConnections

GOOGLE_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/gmail.modify")
PROTON_ADDRESS = "alana@proton.test"


@dataclass
class Boxes(ConnectionResources):
    """One mailbox per connection, named by `addresses`, shared unless its id is in `kept`; the real gate decides."""

    held: HeldConnections
    addresses: dict[int, str]
    kept: set[int]

    def _boxes(self) -> list[tuple[Connection, Resource]]:
        return [(o.connection, Resource(self.addresses[o.connection.id], "mailbox", self.addresses[o.connection.id],
                                        o.connection.id not in self.kept))
                for o in self.held.held.values()]

    async def of_household(self, household_id: int, person_id: int | None = None) -> dict[int, tuple[Resource, ...]]:
        return {c.id: (r,) for c, r in self._boxes()}

    async def listed(self, connection_id: int, household_id: int, found: Sequence[Listed]) -> tuple[Resource, ...]:
        return ()

    async def share(self, connection_id: int, household_id: int, person_id: int, ref: str,
                    shared: bool) -> Resource | None:
        return None

    async def usable(self, use: Use, changing: bool, kind: ResourceKind = "mailbox") -> tuple[Usable, ...]:
        return tuple(Usable(c, r) for c, r in self._boxes() if permits(use, changing, c, r, True))


def world(*connections: tuple[str, str, int | None, tuple[str, ...], Needs | None], kept: Sequence[int] = ()) -> None:
    """Each connection as (kind, address, person, scopes, needs), numbered from 1, behind a router that reads Google
    only (Proton is not wired)."""
    wire(FakeGmail([message("g1", "Field trip", 1_762_000_000_000)]))
    services.register(Mailbox, RoutedMailbox({"google": services.get(Mailbox)}))
    held, addresses = HeldConnections(), dict[int, str]()
    for n, (kind, address, person, scopes, needs) in enumerate(connections, 1):
        connection = Connection(n, HOME, kind, "https://x.test", ALANA, EPOCH, EPOCH, person, "", needs, scopes)
        held.held[(HOME, f"{kind}{n}")] = Opened(connection, "secret")
        addresses[n] = address
    services.register(Connections, held)
    services.register(ConnectionResources, Boxes(held, addresses, set(kept)))


def boxes(alone: bool = True) -> list[dict[str, Any]]:
    result = asyncio.run(MailTools(Use(HOME, ALANA, alone), 8000).call(ToolCall("c", "mail_boxes", {})))
    assert not result.is_error, result.content
    return json.loads(result.content)["mailboxes"]


def test_a_proton_connection_no_adapter_reads_is_listed_with_its_reason_and_gmail_still_is() -> None:
    world(("google", ADDRESS, ALANA, GOOGLE_SCOPES, None), ("proton", PROTON_ADDRESS, ALANA, (), None))
    rows = {r["address"]: r for r in boxes()}
    assert rows[PROTON_ADDRESS]["unavailable"] == "not_supported"
    assert "unavailable" not in rows[ADDRESS] and rows[ADDRESS]["syncing"] is False


def test_a_connection_that_needs_reconnecting_says_so_by_its_field() -> None:
    world(("google", ADDRESS, ALANA, GOOGLE_SCOPES, "reconnect"), ("google", "b@gmail.test", ALANA, GOOGLE_SCOPES, None))
    rows = {r["address"]: r for r in boxes()}
    assert rows[ADDRESS]["unavailable"] == "needs_reconnect" and "unavailable" not in rows["b@gmail.test"]
    assert "hint" not in rows[ADDRESS] and "status" not in rows[ADDRESS]


def test_a_connection_that_needs_its_login_is_signed_out() -> None:
    world(("google", ADDRESS, ALANA, GOOGLE_SCOPES, "login"))
    assert boxes()[0]["unavailable"] == "signed_out"


def test_a_connection_granted_no_read_scope_is_listed_missing_the_scope() -> None:
    world(("google", ADDRESS, ALANA, GOOGLE_SCOPES, None), ("google", "b@gmail.test", ALANA, ("openid", "email"), None))
    rows = {r["address"]: r for r in boxes()}
    assert rows["b@gmail.test"]["unavailable"] == "missing_scope" and "unavailable" not in rows[ADDRESS]


def test_a_mailbox_the_owner_kept_is_listed_not_shared_without_its_address() -> None:
    world(("google", ADDRESS, None, GOOGLE_SCOPES, None), ("google", "b@gmail.test", ALANA, GOOGLE_SCOPES, None), kept=[2])
    rows = boxes(alone=False)
    assert [r["address"] for r in rows if "address" in r] == [ADDRESS]
    assert [r for r in rows if "address" not in r] == [{"shared": False, "unavailable": "not_shared"}]
    assert {r["address"] for r in boxes(alone=True)} == {ADDRESS, "b@gmail.test"}


def test_the_listing_logs_a_count_per_reason_and_no_address(caplog: pytest.LogCaptureFixture) -> None:
    world(("google", ADDRESS, ALANA, GOOGLE_SCOPES, None), ("proton", PROTON_ADDRESS, ALANA, (), None))
    with caplog.at_level(logging.INFO):
        boxes()
    fields = next(r.__dict__["fields"] for r in caplog.records if r.msg == "mail.boxes")
    assert fields["listed"] == 2 and fields["not_supported"] == 1 and fields["not_shared"] == 0
    assert not any("proton.test" in str(v) or "gmail.test" in str(v) for v in fields.values())
