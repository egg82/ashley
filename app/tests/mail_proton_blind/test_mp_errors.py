"""A refused login or an unreachable Bridge is an error that says so, never an empty result (design: "IMAP login failure
surfaces as a clear error"; reasons in `ashley.mail.model`: `unreachable` is "no answer in time, a server error, or an
answer that is not the provider's API")."""

import pytest
from mail_proton_blind_support import ALANA_ADDRESS, DRAFT, LABELS, READ, SEARCH, SEND, Box, World, data, failed, stock
from mail_proton_blind_support import PASSWORD

REFUSED = ("needs_reconnect", "refused")


def test_a_bridge_password_bridge_refuses_is_an_error_on_every_read_and_never_an_empty_list(world: World) -> None:
    box = world.box(password="not-the-password")
    stock(box)
    turn = world.turn()
    for got in (turn.call(LABELS, mailbox=ALANA_ADDRESS), turn.call(SEARCH, mailbox=ALANA_ADDRESS),
                turn.call(READ, mailbox=ALANA_ADDRESS, id="<m1@school.test>")):
        failed(got, *REFUSED)
        assert "syncing" not in got.content and "unreachable" not in got.content and '"messages"' not in got.content
    assert box.account.logins == 0


def test_a_refused_login_stops_a_send_and_a_draft(world: World) -> None:
    box = world.box(password="not-the-password")
    args = {"mailbox": ALANA_ADDRESS, "to": ["dana@club.test"], "subject": "Hi", "body": "Hello"}
    failed(world.turn().call(SEND, **args), *REFUSED)
    failed(world.turn().call(DRAFT, **args), *REFUSED)
    assert world.bridge.smtp.delivered == [] and box.account.commands == []


def test_a_login_that_works_is_made_with_the_accounts_own_address_and_password(world: World, alana: Box) -> None:
    other = world.box("sam@proton.test", who="sam", password=PASSWORD)
    stock(alana)
    assert data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))["messages"]
    assert alana.account.logins >= 1 and other.account.logins == 0


@pytest.mark.parametrize("listener", ["imap", "smtp"])
def test_a_bridge_that_is_not_listening_is_unreachable(world: World, alana: Box, listener: str) -> None:
    stock(alana)
    args = {"mailbox": ALANA_ADDRESS, "to": ["dana@club.test"], "subject": "Hi", "body": "Hello"}
    if listener == "imap":
        world.bridge.imap_listener.stop()
        failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "unreachable")
        failed(world.turn().call(READ, mailbox=ALANA_ADDRESS, id="<m1@school.test>"), "unreachable")
        failed(world.turn().call(DRAFT, **args), "unreachable")
    else:
        world.bridge.smtp_listener.stop()
        failed(world.turn().call(SEND, **args), "unreachable")
        assert data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))["messages"]


def test_an_answer_that_is_not_imap_is_unreachable(world: World, alana: Box) -> None:
    stock(alana)
    world.bridge.imap_behaviour.greeting = "HTTP/1.1 400 Bad Request"
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "unreachable")


def test_a_connection_dropped_mid_conversation_is_unreachable_not_an_empty_list(world: World, alana: Box) -> None:
    stock(alana)
    world.bridge.imap_behaviour.drop_on = "SELECT"
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox"), "unreachable")
    world.bridge.imap_behaviour.drop_on = "LOGIN"
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS), "unreachable", *REFUSED)


def test_the_mailbox_works_again_when_bridge_does(world: World, alana: Box) -> None:
    stock(alana)
    world.bridge.imap_behaviour.drop_on = "SELECT"
    failed(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox"), "unreachable")
    world.bridge.imap_behaviour.drop_on = None
    assert len(data(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="inbox"))["messages"]) == 3
