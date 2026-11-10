"""A label change is a folder copy or move under `Labels/`, applied to every named message or to none (design: "label
change = folder copy/move under Labels/"; `Mailbox.change`: each id must name a message whose sender and subject start with
the target's, `refused` when one does not, `not_found` for an id or a label that is none of the mailbox's, `refused` for a
change that changes nothing)."""

from typing import Any

from mail_proton_blind_support import (ALANA_ADDRESS, LABEL, M1, M2, M3, M5, M6, SEARCH, SUBJECTS, Box, World, data, failed,
                                       rows, snapshot, stock, target)


def row(world: World, subject: str) -> dict[str, Any]:
    return next(r for r in rows(world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="")) if r["subject"] == subject)


def change(world: World, *subjects: str, **over: object) -> object:
    got = world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row(world, s)) for s in subjects], **over)
    return data(got) if not got.is_error else got


def test_adding_a_label_copies_the_message_into_that_label_and_leaves_it_where_it_was(world: World, alana: Box) -> None:
    stock(alana)
    got = change(world, SUBJECTS[M2], add=["School"])
    assert got == {"changed": 1}
    assert alana.account.where(M2) == ["INBOX", "Labels/School"]
    assert alana.account.where(M1) == ["INBOX", "Labels/School"]
    assert row(world, SUBJECTS[M2])["labels"] == ["School"] and row(world, SUBJECTS[M2])["folder"] == "inbox"
    assert not [c for c in alana.account.commands if c[0] in ("CREATE", "DELETE", "RENAME")]


def test_the_id_does_not_change_when_a_label_does(world: World, alana: Box) -> None:
    stock(alana)
    before = row(world, SUBJECTS[M2])["id"]
    change(world, SUBJECTS[M2], add=["School"])
    assert row(world, SUBJECTS[M2])["id"] == before


def test_removing_a_label_deletes_that_copy_only(world: World, alana: Box) -> None:
    stock(alana)
    assert change(world, SUBJECTS[M1], remove=["School"]) == {"changed": 1}
    assert alana.account.where(M1) == ["INBOX"]
    assert row(world, SUBJECTS[M1])["labels"] == []
    assert alana.account.where(M6) == ["Archive", "Labels/Receipts"]


def test_one_call_labels_several_messages(world: World, alana: Box) -> None:
    stock(alana)
    assert change(world, SUBJECTS[M1], SUBJECTS[M2], SUBJECTS[M3], add=["Receipts"]) == {"changed": 3}
    assert alana.account.where(M1) == ["INBOX", "Labels/Receipts", "Labels/School"]
    for mid in (M2, M3):
        assert alana.account.where(mid) == ["INBOX", "Labels/Receipts"]


def test_a_message_that_has_several_labels_keeps_the_others(world: World, alana: Box) -> None:
    stock(alana)
    change(world, SUBJECTS[M1], add=["Receipts"])
    change(world, SUBJECTS[M1], remove=["School"])
    assert alana.account.where(M1) == ["INBOX", "Labels/Receipts"]


def test_moving_to_the_archive_takes_it_out_of_the_inbox_and_leaves_its_labels(world: World, alana: Box) -> None:
    stock(alana)
    assert change(world, SUBJECTS[M1], folder="archive") == {"changed": 1}
    assert alana.account.where(M1) == ["Archive", "Labels/School"]
    assert row(world, SUBJECTS[M1])["folder"] == "archive" and row(world, SUBJECTS[M1])["labels"] == ["School"]


def test_each_move_puts_the_message_in_that_folder_alone(world: World, alana: Box) -> None:
    stock(alana)
    change(world, SUBJECTS[M2], folder="trash")
    assert alana.account.where(M2) == ["Trash"]
    change(world, SUBJECTS[M3], folder="spam")
    assert alana.account.where(M3) == ["Spam"]
    got = world.turn().call(SEARCH, mailbox=ALANA_ADDRESS, folder="spam")
    assert {r["subject"] for r in rows(got)} == {SUBJECTS[M3], SUBJECTS[M5]}


def test_a_message_can_be_moved_back_to_the_inbox(world: World, alana: Box) -> None:
    stock(alana)
    change(world, SUBJECTS[M6], folder="inbox")
    assert alana.account.where(M6) == ["INBOX", "Labels/Receipts"]


def test_unread_sets_and_clears_the_read_state(world: World, alana: Box) -> None:
    stock(alana)
    change(world, SUBJECTS[M1], unread=False)
    assert alana.account.unread(M1) is False
    change(world, SUBJECTS[M2], unread=True)
    assert alana.account.unread(M2) is True
    assert row(world, SUBJECTS[M2])["unread"] is True and row(world, SUBJECTS[M1])["unread"] is False


def test_nothing_is_deleted_for_good(world: World, alana: Box) -> None:
    stock(alana)
    change(world, SUBJECTS[M2], folder="trash")
    change(world, SUBJECTS[M1], folder="archive", add=["Receipts"], remove=["School"], unread=False)
    assert alana.account.where(M2) == ["Trash"] and alana.account.where(M1) == ["Archive", "Labels/Receipts"]
    assert not [c for c in alana.account.commands if c[0] in ("DELETE", "RENAME", "CREATE")]


def test_a_label_that_is_none_of_the_mailboxs_refuses_the_call_and_creates_nothing(world: World, alana: Box) -> None:
    stock(alana)
    before = snapshot(alana)
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row(world, SUBJECTS[M2]))], add=["Nope"]), "not_found")
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row(world, SUBJECTS[M2]))], add=["School", "Nope"]))
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row(world, SUBJECTS[M2]))], remove=["Nope"]))
    assert snapshot(alana) == before


def test_a_name_that_is_a_folder_or_a_path_is_not_a_label(world: World, alana: Box) -> None:
    stock(alana)
    before = snapshot(alana)
    for name in ("inbox", "INBOX", "Trash", "Labels/School", "All Mail", "../Trash"):
        failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row(world, SUBJECTS[M2]))], add=[name]))
    assert snapshot(alana) == before


def test_one_message_whose_sender_or_subject_is_not_what_was_shown_refuses_the_whole_call(world: World, alana: Box) -> None:
    stock(alana)
    before = snapshot(alana)
    good, other = target(row(world, SUBJECTS[M2])), target(row(world, SUBJECTS[M3]))
    for wrong in ({**other, "from": "Mallory <m@evil.test>"}, {**other, "subject": "Something else entirely"}):
        failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[good, wrong], add=["School"], folder="trash"), "refused")
        assert snapshot(alana) == before


def test_a_target_that_gives_the_start_of_the_sender_and_subject_is_enough(world: World, alana: Box) -> None:
    stock(alana)
    got = world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[{"id": row(world, SUBJECTS[M2])["id"], "from": "Bob", "subject": "Invoice"}],
                            add=["School"])
    assert data(got) == {"changed": 1}


def test_an_id_that_is_no_message_of_the_mailbox_refuses_the_whole_call(world: World, alana: Box) -> None:
    stock(alana)
    before = snapshot(alana)
    good = target(row(world, SUBJECTS[M2]))
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[good, {"id": "<ghost@x.test>", "from": "a", "subject": "b"}],
                             add=["School"]), "not_found")
    assert snapshot(alana) == before


def test_a_label_both_added_and_removed_changes_nothing(world: World, alana: Box) -> None:
    stock(alana)
    before = snapshot(alana)
    failed(world.turn().call(LABEL, mailbox=ALANA_ADDRESS, messages=[target(row(world, SUBJECTS[M2]))], add=["School"], remove=["School"]))
    assert snapshot(alana) == before
