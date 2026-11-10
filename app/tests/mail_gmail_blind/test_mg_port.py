"""The mail port and the Gmail adapter's boundary (design: "Mail, a new system: a port ... over neutral records, with an
adapter per provider", "`gmail.readonly` added to the kind", "`Port` gains `mail`", "`MailFailed(reason)`")."""

import dataclasses
from typing import Any, get_args

import pytest
from ashley import services
from ashley.connections.kinds import ConnectionKinds, OAuth
from ashley.connections.model import Port
from ashley.mail.gmail import GmailMailbox
from ashley.mail.mailbox import Mailbox, MailFailed
from ashley.mail.model import Header, MailQuery, Message, Reason
from ashley.tools.mail import MailTools
from ashley.wiring import CONNECTION_KINDS
from mail_gmail_blind_support import ADDRESS, BOXES, LABELS, READ, SEARCH, World, day, message

REASONS = ("refused", "unreachable", "syncing", "needs_reconnect", "not_found")


def test_the_port_the_adapter_and_the_tools_are_where_the_design_names_them() -> None:
    assert issubclass(GmailMailbox, Mailbox) and GmailMailbox is not Mailbox
    assert MailTools is not None


@pytest.mark.parametrize("record", [Header, Message, MailQuery])
def test_the_records_are_frozen_values(record: type) -> None:
    params: Any = getattr(record, "__dataclass_params__", None)
    assert dataclasses.is_dataclass(record) and params is not None and params.frozen is True


@pytest.mark.parametrize("reason", REASONS)
def test_a_failure_carries_its_reason(reason: Reason) -> None:
    failure = MailFailed(reason)
    assert isinstance(failure, Exception) and failure.reason == reason


def test_the_port_list_gains_mail() -> None:
    assert "mail" in get_args(Port)


def test_the_google_kind_implements_the_mail_port_and_asks_for_gmail_modify_and_nothing_wider() -> None:
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    kind = services.get(ConnectionKinds).get("google")
    assert kind is not None and "mail" in kind.ports and isinstance(kind.connect, OAuth)
    last = {s.rsplit("/", 1)[-1].removeprefix("userinfo.") for s in kind.connect.scopes}
    assert {"openid", "email", "gmail.modify"} <= last
    assert not last & {"gmail.compose", "gmail.send", "gmail.insert", "gmail.labels", "mail.google.com"}
    assert kind in services.get(ConnectionKinds).of_port("mail")


def use_all(world: World) -> None:
    turn = world.turn()
    turn.call(BOXES)
    turn.call(LABELS, mailbox=ADDRESS)
    turn.call(SEARCH, mailbox=ADDRESS)
    turn.call(READ, mailbox=ADDRESS, id="m1")


def test_every_request_is_a_get_to_gmails_api_with_the_token_in_the_header(world: World) -> None:
    world.fake.add(message("m1", day(3, 4), "Menu", text="soup", attachments=(("a.pdf", "application/pdf", 3),)))
    world.connect()
    use_all(world)
    seen = world.fake.calls("gmail")
    assert seen and {s.method for s in seen} == {"GET"}
    assert world.fake.calls("stray") == []
    assert all(s.bearer and "access_token" not in s.query for s in seen)

