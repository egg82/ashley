"""What Proton's mailbox logs (design: "`mail.call` (connection id, mailbox's resource id, call, status, count,
duration_ms) ... None carries an address, a subject, a body, a query, a token, a password or the vault"). The fake Bridge
echoes the recipient and a secret-looking word in its error replies, so a log that copies a server's words shows it."""

import logging

import pytest
from mail_proton_blind_imap_support import LEAK
from mail_proton_blind_support import (ALANA_ADDRESS, DRAFT, LABEL, LABELS, M1, PASSWORD, READ, SEARCH, SEND, SUBJECTS, Box, World,
                                       rows, stock, target)

SUBJECT, BODY, TO = "Zebra quarterly ledger", "the vault code is swordfish-9917", "zelda.quux@hyrule.test"
QUERY = "Quokka-Ferret-Gambit"


def text_of(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''}" for r in caplog.records)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def use_all(world: World) -> None:
    turn = world.turn()
    found = rows(turn.call(SEARCH, mailbox=ALANA_ADDRESS, text=QUERY, subject="Trip", **{"from": "pat@school.test"}))
    everything = rows(turn.call(SEARCH, mailbox=ALANA_ADDRESS))
    row = next(r for r in everything if r["subject"] == SUBJECTS[M1])
    assert found == []
    turn.call("mail_boxes")
    turn.call(LABELS, mailbox=ALANA_ADDRESS)
    turn.call(READ, mailbox=ALANA_ADDRESS, id=row["id"])
    turn.call(DRAFT, mailbox=ALANA_ADDRESS, to=[TO], cc=["quinn.ray@hyrule.test"], subject=SUBJECT, body=BODY)
    turn.call(SEND, mailbox=ALANA_ADDRESS, to=[TO], subject=SUBJECT, body=BODY)
    turn.call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row)], add=["Receipts"])


def failures(world: World) -> None:
    world.bridge.smtp_behaviour.refuse_rcpt = {TO}
    args = {"mailbox": ALANA_ADDRESS, "to": [TO], "subject": SUBJECT, "body": BODY}
    world.turn().call(SEND, **args)
    world.bridge.smtp_behaviour.refuse_rcpt, world.bridge.smtp_behaviour.data_code = set(), 451
    world.turn().call(SEND, **args)
    world.bridge.smtp_behaviour.data_code, world.bridge.smtp_behaviour.drop_after_data = 250, True
    world.turn().call(SEND, **args)
    world.bridge.smtp_behaviour.drop_after_data = False
    world.bridge.imap_behaviour.drop_on = "SELECT"
    world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, text=QUERY)
    world.bridge.imap_behaviour.drop_on, world.bridge.imap_behaviour.greeting = None, "HTTP/1.1 400 no"
    world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, text=QUERY)
    world.bridge.imap_behaviour.greeting = None
    bad = world.box("bad@proton.test", label="bad", password="wrong-pw-9917")
    world.turn().call(SEARCH, mailbox=bad.address, text=QUERY)
    world.turn().call(SEND, mailbox=bad.address, to=[TO], subject=SUBJECT, body=BODY)
    syncing = world.box("sync@proton.test", label="sync", synced=False)
    world.turn().call(SEARCH, mailbox=syncing.address, text=QUERY)


def test_each_call_logs_one_mail_call_with_its_outcome_and_duration(world: World, alana: Box, caplog: pytest.LogCaptureFixture) -> None:
    stock(alana)
    caplog.set_level(logging.DEBUG)
    use_all(world)
    calls = events(caplog, "mail.call")
    assert len(calls) >= 7
    for fields in calls:
        assert {"call", "status", "count", "duration_ms"} <= set(fields), fields
    assert {str(f["status"]) for f in calls} == {"ok"}


def test_a_failed_call_logs_its_reason_as_its_status(world: World, alana: Box, caplog: pytest.LogCaptureFixture) -> None:
    stock(alana)
    caplog.set_level(logging.DEBUG)
    failures(world)
    statuses = {str(f["status"]) for f in events(caplog, "mail.call")}
    assert {"unreachable", "syncing"} <= statuses and statuses & {"refused", "needs_reconnect"}


def test_no_log_line_carries_an_address_subject_body_label_sender_query_or_server_reply(world: World, alana: Box,
                                                                                         caplog: pytest.LogCaptureFixture) -> None:
    stock(alana)
    caplog.set_level(logging.DEBUG)
    use_all(world)
    failures(world)
    logged = text_of(caplog).lower()
    assert "mail.call" in logged
    leaked = [s for s in (TO, "zelda", "quinn.ray", SUBJECT, "zebra", BODY, "swordfish", LEAK, ALANA_ADDRESS, "alana@", "bad@proton",
                          "sync@proton", "pat@school", "bob@shop", "school.test", "hyrule", QUERY, "quokka",
                          "School", "Receipts", "Trip money", "bring ten dollars", "Pat <", "Invoice")
              if s.lower() in logged]
    assert not leaked, leaked


def test_no_log_line_carries_a_password_or_a_login_command(world: World, alana: Box, caplog: pytest.LogCaptureFixture) -> None:
    stock(alana)
    caplog.set_level(logging.DEBUG)
    use_all(world)
    failures(world)
    logged = text_of(caplog)
    assert "mail.call" in logged
    assert not [s for s in (PASSWORD, "wrong-pw-9917", "AUTHENTICATE", "LOGIN ", "AUTH PLAIN", "AUTH LOGIN") if s in logged]
    assert not [s for s in (PASSWORD, "wrong-pw-9917") if s in logged.lower()]

