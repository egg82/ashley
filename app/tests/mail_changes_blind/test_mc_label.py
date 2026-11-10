"""`mail_label`: the labels, folder and read state a call names change on the messages it lists, and nothing else (design:
"`MailChange` (labels to add and remove, a folder to move to, read or unread)"; "the adapter refuses a call whose sender or
subject does not match the id"; "at most `max_change_ids`"; "Moving to the trash is offered; deleting forever is not")."""

import json
from datetime import UTC, datetime
from email.header import Header
from pathlib import Path

import pytest
from ashley.inference.model import ToolResult
from ashley.mail import config
from mail_changes_blind_support import (LABEL, M1, M2, World, entry, failed, label_args, labels_now, message,
                                        untouched)

ALLOWED_PATHS = ("/messages/m1/modify", "/messages/m2/modify", "/messages/m3/modify", "/messages/m4/modify",
                 "/messages/m1/trash", "/messages/m2/trash", "/messages/m4/untrash", "/messages/batchModify")


def run(world: World, *entries: dict[str, str], **change: object) -> ToolResult:
    return world.turn().call(LABEL, **label_args(*entries, **change))


def test_labels_are_added_and_removed_on_the_listed_messages_only(stocked: World) -> None:
    got = run(stocked, M1, M2, add_labels=["School"], remove_labels=["Receipts"])
    assert not got.is_error, got.content
    assert stocked.fake.labels_of("m1") == {"INBOX", "UNREAD", "Label_12"}
    assert stocked.fake.labels_of("m2") == {"INBOX", "Label_12"}
    assert stocked.fake.labels_of("m3") == {"INBOX"} and stocked.fake.labels_of("m4") == {"TRASH"}
    assert all(w.path in ALLOWED_PATHS for w in stocked.fake.writes()), stocked.fake.writes()
    assert stocked.fake.sent == [] and stocked.fake.drafts == [] and stocked.fake.forbidden == []


def test_adding_alone_keeps_what_the_message_has(stocked: World) -> None:
    assert not run(stocked, M1, add_labels=["School"]).is_error
    assert stocked.fake.labels_of("m1") == {"INBOX", "UNREAD", "Label_13", "Label_12"}


def test_removing_alone_adds_nothing(stocked: World) -> None:
    assert not run(stocked, M1, remove_labels=["Receipts"]).is_error
    assert stocked.fake.labels_of("m1") == {"INBOX", "UNREAD"}


def test_read_and_unread_toggle_only_the_unread_state(stocked: World) -> None:
    assert not run(stocked, M1, unread=False).is_error
    assert stocked.fake.labels_of("m1") == {"INBOX", "Label_13"}
    assert not run(stocked, M2, unread=True).is_error
    assert stocked.fake.labels_of("m2") == {"INBOX", "UNREAD"}


def test_a_move_to_the_trash_leaves_the_inbox_and_keeps_everything_else(stocked: World) -> None:
    assert not run(stocked, M1, folder="trash").is_error
    assert stocked.fake.labels_of("m1") == {"TRASH", "UNREAD", "Label_13"}
    assert stocked.fake.labels_of("m2") == {"INBOX"}
    assert [m.id for m in stocked.fake.messages] == ["m1", "m2", "m3", "m4"] and stocked.fake.forbidden == []


def test_a_move_back_to_the_inbox_leaves_the_trash(stocked: World) -> None:
    assert not run(stocked, entry("m4", subject="Old"), folder="inbox").is_error
    assert stocked.fake.labels_of("m4") == {"INBOX"}


@pytest.mark.parametrize("wrong", [entry("m1", subject="Something else"), entry("m1", sender="Mallory <m@evil.test>")],
                         ids=["subject", "sender"])
def test_a_message_whose_sender_or_subject_is_not_the_ids_refuses_the_whole_call(stocked: World, wrong: dict[str, str]) -> None:
    before = labels_now(stocked)
    failed(run(stocked, M2, wrong, add_labels=["School"]))
    untouched(stocked, before)
    assert not run(stocked, M2, add_labels=["School"]).is_error  # control: the right sender and subject are changed


def test_an_id_the_mailbox_does_not_have_refuses_the_whole_call(stocked: World) -> None:
    before = labels_now(stocked)
    failed(run(stocked, M1, entry("ghost"), add_labels=["School"]), "not_found")
    untouched(stocked, before)
    assert not run(stocked, M1, add_labels=["School"]).is_error  # control: the same call without the ghost is made


def test_a_subject_that_was_encoded_on_the_wire_matches_as_its_text(world: World) -> None:
    sent = Header("Réunion à neuf heures", "utf-8").encode()
    world.fake.add(message("e1", datetime(2026, 3, 5, 12, tzinfo=UTC), "Réunion à neuf heures", subject_header=sent))
    world.connect()
    assert not run(world, entry("e1", subject="Réunion à neuf heures"), add_labels=["School"]).is_error
    assert "Label_12" in world.fake.labels_of("e1")


@pytest.mark.parametrize("change", [{"add_labels": ["Nonesuch"]}, {"remove_labels": ["Nonesuch"]},
                                    {"add_labels": ["TRASH"]}, {"add_labels": ["SPAM"]}, {"remove_labels": ["INBOX"]},
                                    {"add_labels": ["UNREAD"]}, {"folder": "nowhere"}, {"folder": "delete"},
                                    {"folder": "School"}, {"add_labels": "School"}, {"unread": "yes"}],
                         ids=["unknown-add", "unknown-remove", "system-trash", "system-spam", "system-inbox",
                              "system-unread", "unknown-folder", "folder-delete", "label-as-folder", "label-not-a-list",
                              "unread-not-a-flag"])
def test_what_is_not_a_household_label_or_a_folder_changes_nothing_and_creates_nothing(stocked: World, change: dict[str, object]) -> None:
    before = labels_now(stocked)
    failed(run(stocked, M1, **change))
    untouched(stocked, before)
    assert not run(stocked, M1, add_labels=["School"]).is_error  # control: a household label on the same message is made


def test_a_call_with_no_messages_or_no_change_does_nothing(stocked: World) -> None:
    before = labels_now(stocked)
    run(stocked, add_labels=["School"])
    run(stocked, M1)
    untouched(stocked, before)
    assert not run(stocked, M1, add_labels=["School"]).is_error  # control: a call with both is made


def stocked_many(world: World, count: int) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for i in range(count):
        world.fake.add(message(f"x{i}", datetime(2026, 4, 1, tzinfo=UTC), f"Note {i}", sender="Pat <pat@club.test>"))
        entries.append(entry(f"x{i}", "Pat <pat@club.test>", f"Note {i}"))
    return entries


def most() -> int:
    raw = json.loads(Path(config.FILE).read_text())
    assert isinstance(raw["max_change_ids"], int) and 0 < raw["max_change_ids"] <= 1000
    return int(raw["max_change_ids"])


def test_as_many_ids_as_the_most_are_changed(world: World) -> None:
    world.connect()
    entries = stocked_many(world, most())
    assert not run(world, *entries, add_labels=["School"]).is_error
    assert all("Label_12" in world.fake.labels_of(e["id"]) for e in entries)


def test_one_id_more_than_the_most_refuses_the_call_and_changes_none(world: World) -> None:
    world.connect()
    entries = stocked_many(world, most() + 1)
    before = labels_now(world)
    failed(run(world, *entries, add_labels=["School"]))
    untouched(world, before)
    assert not run(world, *entries[:-1], add_labels=["School"]).is_error  # control: the most ids are made
