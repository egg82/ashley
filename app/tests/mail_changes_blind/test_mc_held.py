"""A consequential change after mail was read (a send, a move to the trash) is held by `Outside`, shown in the pending block in full, and runs exactly once, with the
arguments that were stored, when a later untainted private turn calls `carry_out` (design: "Reading mail taints the turn,
so every change after it is held for `carry_out`, and the pending block shows each held call's arguments in full";
"A held send or label is a proposal row and runs once")."""

import pytest
from ashley.tools import outside_config
from mail_changes_blind_support import (ADDRESS, DRAFT, LABEL, Guarded, M1, M2, READ, SEARCH, SEND, World, label_args,
                                        labels_now, send_args, untouched)

CONFIG = outside_config.load()
READS = {SEARCH: {"mailbox": ADDRESS}, READ: {"mailbox": ADDRESS, "id": "m1"}}
SENDS = send_args(to=["dana@club.test", "ella@club.test"], cc=["fay@club.test"], subject="Forwarded key",
                  body="Here is the key.\nDo not share.", reply_to="m1")


def tainted_turn(world: World, tool: str = READ) -> Guarded:
    turn = world.guarded()
    assert not turn.call(tool, **READS[tool]).is_error
    assert turn.tainted == tool
    return turn


@pytest.mark.parametrize("read", [SEARCH, READ])
@pytest.mark.parametrize(("tool", "args"), [(SEND, SENDS),
                                            (LABEL, label_args(M1, M2, add_labels=["School"], folder="trash"))])
def test_a_consequential_change_after_a_read_is_held_and_nothing_is_written(stocked: World, read: str, tool: str, args: dict[str, object]) -> None:
    before = labels_now(stocked)
    turn = tainted_turn(stocked, read)
    got = turn.call(tool, **args)
    assert not got.is_error and got.content.startswith(CONFIG.held)
    untouched(stocked, before)
    assert stocked.fake.writes() == []
    assert turn.pending() != ""


def test_the_pending_block_shows_a_sends_recipients_subject_and_body_in_full(stocked: World) -> None:
    turn = tainted_turn(stocked)
    turn.call(SEND, **SENDS)
    block = turn.pending()
    for shown in ("dana@club.test", "ella@club.test", "fay@club.test", "Forwarded key", "Here is the key.\\nDo not share."):
        assert shown in block, shown
    assert SEND not in block and "Sent an email" in block, "the change is named plainly, never by its tool"


def test_the_pending_block_shows_each_trashed_message_by_id_sender_and_subject(stocked: World) -> None:
    turn = tainted_turn(stocked)
    turn.call(LABEL, **label_args(M1, M2, add_labels=["School"], folder="trash"))
    block = turn.pending()
    for shown in ("m1", "m2", "Alice <alice@school.test>", "Hello", "Bob <bob@shop.test>", "Invoice", "School", "trash"):
        assert shown in block, shown


def test_a_held_send_runs_once_with_the_stored_arguments_in_a_later_untainted_turn(stocked: World) -> None:
    turn = tainted_turn(stocked)
    turn.call(SEND, **SENDS)
    assert stocked.fake.sent == []
    later = stocked.guarded()
    assert "carry_out" in later.names()
    got = later.carry_out()
    assert not got.is_error, got.content
    assert len(stocked.fake.sent) == 1
    one = stocked.fake.sent[0]
    assert one.to == ("dana@club.test", "ella@club.test") and one.cc == ("fay@club.test",)
    assert one.subject == "Forwarded key" and one.body == "Here is the key.\nDo not share."
    assert one.in_reply_to == "<m1@mail.test>" and one.thread_id == "th-m1"
    assert [w.path for w in stocked.fake.writes()] == ["/messages/send"]
    assert later.carry_out().is_error and len(stocked.fake.sent) == 1


def test_a_held_trash_runs_once_when_it_is_carried_out(stocked: World) -> None:
    turn = tainted_turn(stocked)
    turn.call(LABEL, **label_args(M2, folder="trash"))
    assert stocked.fake.labels_of("m2") == {"INBOX"}
    assert not stocked.guarded().carry_out().is_error
    assert "TRASH" in stocked.fake.labels_of("m2") and "INBOX" not in stocked.fake.labels_of("m2")
    assert stocked.fake.labels_of("m1") == {"INBOX", "UNREAD", "Label_13"}


def test_a_draft_after_a_read_is_stored_at_once_and_is_not_held(stocked: World) -> None:
    turn = tainted_turn(stocked)
    got = turn.call(DRAFT, **SENDS)
    assert not got.is_error and got.content != CONFIG.held
    assert len(stocked.fake.drafts) == 1 and stocked.fake.sent == []
    assert turn.pending() is None or not turn.pending()


def test_a_label_after_a_read_runs_at_once_and_is_not_held(stocked: World) -> None:
    turn = tainted_turn(stocked)
    got = turn.call(LABEL, **label_args(M2, add_labels=["School"]))
    assert not got.is_error and got.content != CONFIG.held
    assert stocked.fake.labels_of("m2") == {"INBOX", "Label_12"}


def test_several_held_changes_run_in_order_once_each(stocked: World) -> None:
    turn = tainted_turn(stocked)
    turn.call(LABEL, **label_args(M2, folder="trash"))
    turn.call(SEND, **SENDS)
    turn.call(SEND, **SENDS)
    assert len([ln for ln in turn.pending().splitlines() if not ln.startswith("  ")]) == 2
    assert not stocked.guarded().carry_out().is_error
    assert len(stocked.fake.sent) == 1 and "TRASH" in stocked.fake.labels_of("m2")
    assert [w.path for w in stocked.fake.writes()][-1] == "/messages/send"


def test_a_turn_that_read_mail_cannot_carry_out_what_is_held(stocked: World) -> None:
    tainted_turn(stocked).call(SEND, **SENDS)
    later = stocked.guarded()
    assert not later.call(SEARCH, mailbox=ADDRESS).is_error
    assert "carry_out" not in later.names() and later.carry_out().is_error
    assert stocked.fake.sent == []


def test_a_turn_that_started_tainted_cannot_carry_out(stocked: World) -> None:
    tainted_turn(stocked).call(SEND, **SENDS)
    woken = stocked.guarded(taint="watch")
    assert "carry_out" not in woken.names() and woken.carry_out().is_error
    assert stocked.fake.sent == []


def test_the_turn_that_held_a_change_cannot_agree_to_it(stocked: World) -> None:
    turn = tainted_turn(stocked)
    turn.call(SEND, **SENDS)
    assert turn.carry_out().is_error and stocked.fake.sent == []


def test_a_connection_that_needs_reconnecting_by_then_sends_nothing(stocked: World) -> None:
    tainted_turn(stocked).call(SEND, **SENDS)
    stocked.mark_reconnect(stocked.connection)
    got = stocked.guarded().carry_out()
    assert "needs_reconnect" in got.content
    assert stocked.fake.sent == []
