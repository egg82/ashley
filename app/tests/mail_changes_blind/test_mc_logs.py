"""What changes log (design: "`mail.call` (connection id, mailbox's resource id, call, status, count, duration_ms) ... None
carries an address, a subject, a body, a query, a token, a password or the vault")."""

import logging
from datetime import UTC, datetime

import pytest
from mail_changes_blind_support import (ADDRESS, DRAFT, LABEL, READ, SEARCH, SEED_ACCESS, SEED_REFRESH, SEND, World, entry,
                                        label_args, message, send_args)

SUBJECT, BODY, TO = "Zebra quarterly ledger", "the vault code is swordfish-9917", "zelda.quux@hyrule.test"
SENDER, THEIRS = "Orin Vale <orin@marsh.test>", "Marsh invoice 4412"


def text_of(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.exc_text or ''}" for r in caplog.records)


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def stocked(world: World) -> None:
    world.fake.add(message("p1", datetime(2026, 3, 9, tzinfo=UTC), THEIRS, sender=SENDER, text="pay the marsh bill"))
    world.connect()


def the_changes(world: World) -> None:
    mine = send_args(to=[TO], cc=["quinn.ray@hyrule.test"], subject=SUBJECT, body=BODY)
    turn = world.guarded()
    turn.call(DRAFT, **mine)
    turn.call(SEND, **mine)
    turn.call(LABEL, **label_args(entry("p1", SENDER, THEIRS), add_labels=["School"], remove_labels=["Receipts"]))
    held = world.guarded()
    held.call(READ, mailbox=ADDRESS, id="p1")
    held.call(SEND, **mine)
    held.call(LABEL, **label_args(entry("p1", SENDER, THEIRS), add_labels=["Receipts"]))
    world.guarded().carry_out()
    assert len(world.fake.sent) == 2 and len(world.fake.drafts) == 1 and world.fake.labels_of("p1") != {"INBOX"}


def test_each_change_logs_a_mail_call_with_its_outcome_and_duration(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    the_changes(world)
    calls = events(caplog, "mail.call")
    assert len(calls) >= 3 and world.fake.sent and world.fake.drafts
    for fields in calls:
        assert {"call", "status", "count", "duration_ms"} <= set(fields), fields
    assert {str(f["status"]) for f in calls} == {"ok"}


def test_a_failed_change_logs_its_reason_as_its_status(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    world.fake.gmail_status = 503
    caplog.set_level(logging.DEBUG)
    world.guarded().call(SEND, **send_args())
    assert "unreachable" in [str(f["status"]) for f in events(caplog, "mail.call")]


def test_a_change_that_needs_a_reconnect_logs_that_as_its_status(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    world.mark_reconnect(world.connection)
    caplog.set_level(logging.DEBUG)
    world.guarded().call(SEND, **send_args())
    assert "needs_reconnect" in [str(f["status"]) for f in events(caplog, "mail.call")]


def test_no_log_line_carries_a_recipient_subject_body_label_or_the_senders_words(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    the_changes(world)
    logged = text_of(caplog).lower()
    assert "mail.call" in logged and "outside.held" in logged
    leaked = [s for s in (TO, "zelda", "quinn.ray", SUBJECT, "zebra", BODY, "swordfish", ADDRESS, "orin@marsh", "marsh",
                          "School", "Receipts", "hyrule") if s.lower() in logged]
    assert not leaked, leaked


def test_no_log_line_carries_a_token(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    the_changes(world)
    logged = text_of(caplog)
    assert "mail.call" in logged
    assert not [s for s in (SEED_ACCESS, SEED_REFRESH, *world.fake.secret_values()) if s in logged]


def test_failures_log_no_content_either(world: World, caplog: pytest.LogCaptureFixture) -> None:
    stocked(world)
    caplog.set_level(logging.DEBUG)
    mine = send_args(to=[TO], subject=SUBJECT, body=BODY)
    world.fake.gmail_status = 503
    world.guarded().call(SEND, **mine)
    world.fake.gmail_status, world.fake.gmail_down = None, True
    world.guarded().call(DRAFT, **mine)
    world.guarded().call(SEARCH, mailbox=ADDRESS)
    logged = text_of(caplog)
    assert {"unreachable"} <= {str(f["status"]) for f in events(caplog, "mail.call")}
    assert not [s for s in (TO, SUBJECT, BODY, ADDRESS) if s in logged]
