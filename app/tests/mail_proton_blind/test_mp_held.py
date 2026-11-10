"""Outside's rules hold over Proton (design: "A turn that has read outside words asks before it changes anything"): reading
mail taints the turn, a send or a move to the trash after it is held, shown in full and run once, a draft or a label runs by
its tier; a send the person dictated runs at once."""

import pytest
from ashley.tools import outside_config
from mail_proton_blind_support import (ALANA_ADDRESS, DRAFT, LABEL, M1, M2, READ, SEARCH, SEND, SUBJECTS, Box, Guarded, World, data,
                                       by_subject, rows, snapshot, stock, target)

CONFIG = outside_config.load()
SENDS = {"mailbox": ALANA_ADDRESS, "to": ["dana@club.test", "ella@club.test"], "cc": ["fay@club.test"],
         "subject": "Forwarded key", "body": "Here is the key.\nDo not share."}


def tainted(world: World, tool: str) -> Guarded:
    turn = world.guarded()
    args = {SEARCH: {"mailbox": ALANA_ADDRESS}, READ: {"mailbox": ALANA_ADDRESS, "id": by_subject(world, SUBJECTS[M1])["id"]}}[tool]
    assert not turn.call(tool, **args).is_error
    assert turn.tainted == tool
    return turn


def label_args(world: World) -> dict[str, object]:
    found = {r["subject"]: r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS))}
    return {"mailbox": ALANA_ADDRESS, "messages": [target(found[SUBJECTS[M1]]), target(found[SUBJECTS[M2]])],
            "add": ["Receipts"]}


def test_the_read_tools_of_a_proton_mailbox_declare_outside_and_the_changes_do_not(world: World, alana: Box) -> None:
    specs = {n: s for n, s in world.turn().specs().items() if n.startswith("mail_")}
    assert {n for n, s in specs.items() if s.outside} == {SEARCH, READ}
    assert {n for n, s in specs.items() if not s.reads} == {DRAFT, LABEL, SEND}
    assert set(specs) == {"mail_boxes", "mail_labels", SEARCH, READ, DRAFT, LABEL, SEND}


@pytest.mark.parametrize("read", [SEARCH, READ])
def test_a_send_after_reading_proton_mail_is_held_and_nothing_is_written(world: World, alana: Box, read: str) -> None:
    stock(alana)
    before = snapshot(alana)
    turn = tainted(world, read)
    got = turn.call(SEND, **SENDS)
    assert not got.is_error and got.content.startswith(CONFIG.held)
    assert world.bridge.smtp.attempts == 0 and snapshot(alana) == before
    assert turn.pending() != ""


@pytest.mark.parametrize("read", [SEARCH, READ])
@pytest.mark.parametrize("tool", [DRAFT, LABEL])
def test_a_draft_or_a_label_after_reading_proton_mail_runs_by_its_tier(world: World, alana: Box, read: str, tool: str) -> None:
    stock(alana)
    before = snapshot(alana)
    turn = tainted(world, read)
    args = label_args(world) if tool == LABEL else SENDS
    got = turn.call(tool, **args)
    assert not got.is_error and got.content != CONFIG.held
    assert world.bridge.smtp.attempts == 0 and snapshot(alana) != before


@pytest.mark.parametrize("read", [SEARCH, READ])
def test_a_move_to_the_trash_after_reading_proton_mail_is_held_and_nothing_is_written(world: World, alana: Box, read: str) -> None:
    stock(alana)
    before = snapshot(alana)
    turn = tainted(world, read)
    moved: dict[str, object] = {**label_args(world), "add": [], "folder": "trash"}
    got = turn.call(LABEL, **moved)
    assert not got.is_error and got.content.startswith(CONFIG.held)
    assert snapshot(alana) == before and turn.pending() != ""


def test_the_pending_block_shows_a_sends_recipients_subject_and_body_in_full(world: World, alana: Box) -> None:
    stock(alana)
    turn = tainted(world, READ)
    turn.call(SEND, **SENDS)
    block = turn.pending()
    for shown in ("dana@club.test", "ella@club.test", "fay@club.test", "Forwarded key", "Here is the key.\\nDo not share."):
        assert shown in block, shown


def test_a_held_send_runs_once_with_the_stored_arguments_in_a_later_untainted_turn(world: World, alana: Box) -> None:
    stock(alana)
    turn = tainted(world, READ)
    turn.call(SEND, **SENDS)
    assert world.bridge.smtp.delivered == []
    later = world.guarded()
    assert "carry_out" in later.specs()
    assert not later.carry_out().is_error
    (done,) = world.bridge.smtp.delivered
    assert sorted(done.rcpts) == ["dana@club.test", "ella@club.test", "fay@club.test"] and done.mail_from == ALANA_ADDRESS
    assert b"Do not share." in done.data
    world.guarded().carry_out()
    assert len(world.bridge.smtp.delivered) == 1


def test_a_label_run_after_reading_lands_on_both_messages_with_no_agreement(world: World, alana: Box) -> None:
    stock(alana)
    turn = tainted(world, SEARCH)
    assert not turn.call(LABEL, **label_args(world)).is_error
    assert alana.account.where(M1) == ["INBOX", "Labels/Receipts", "Labels/School"]
    assert alana.account.where(M2) == ["INBOX", "Labels/Receipts"]


def test_a_send_in_a_turn_that_read_nothing_runs_at_once(world: World, alana: Box) -> None:
    turn = world.guarded()
    got = turn.call(SEND, **SENDS)
    assert not got.is_error and got.content != CONFIG.held and len(world.bridge.smtp.delivered) == 1
    assert turn.tainted is None
    assert "sent" in data(got)


def test_listing_the_mailboxes_and_labels_does_not_taint_the_turn(world: World, alana: Box) -> None:
    turn = world.guarded()
    turn.call("mail_boxes")
    turn.call("mail_labels", mailbox=ALANA_ADDRESS)
    assert turn.tainted is None
