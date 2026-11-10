"""`mail_boxes` and `mail_labels` (design: the tools table, "A mailbox is named by its address")."""

from typing import Any

from mail_gmail_blind_support import ABSENT, ADDRESS, BOXES, LABELS, World, as_records, data, dig, failed


def boxes(world: World) -> list[dict[str, Any]]:
    return as_records(dig(data(world.turn().call(BOXES)), "mailboxes"))


def test_boxes_lists_the_connected_gmail_address_as_kept_and_not_syncing(world: World) -> None:
    world.connect()
    [box] = boxes(world)
    assert box["address"] == ADDRESS
    assert box["shared"] is False
    assert box["syncing"] is False


def test_boxes_names_the_address_gmail_says_not_one_the_test_guessed(world: World) -> None:
    world.fake.address = "kim.family@gmail.test"
    world.connect()
    assert [b["address"] for b in boxes(world)] == ["kim.family@gmail.test"]


def test_boxes_lists_only_the_speakers_own_mailbox(world: World) -> None:
    world.connect("alana")
    world.fake.accept("at-sam-0002-ACCESSTOKEN", "rt-sam-0002-REFRESHTOKEN")
    world.connect("sam", access="at-sam-0002-ACCESSTOKEN", refresh="rt-sam-0002-REFRESHTOKEN")
    assert len(boxes(world)) == 1
    data(world.turn().call(LABELS, mailbox=ADDRESS))
    assert set(world.fake.bearers()) == {"at-seed-0001-ACCESSTOKEN"}


def test_labels_lists_the_households_labels_by_name_and_the_inbox(world: World) -> None:
    world.connect()
    got = data(world.turn().call(LABELS, mailbox=ADDRESS))
    text = str(got)
    assert "School" in text and "Receipts" in text
    assert "inbox" in text.lower()


def test_labels_never_shows_gmails_ids_for_the_households_labels(world: World) -> None:
    world.connect()
    text = world.turn().call(LABELS, mailbox=ADDRESS).content
    assert "Label_12" not in text and "Label_13" not in text


def test_a_mailbox_the_person_does_not_hold_is_refused_and_nothing_reaches_gmail(world: World) -> None:
    world.connect()
    result = world.turn().call(LABELS, mailbox="someone.else@gmail.test")
    assert result.is_error
    assert world.fake.calls("gmail") == []


def test_labels_answers_needs_reconnect_not_an_empty_list(world: World) -> None:
    world.mark_reconnect(world.connect())
    failed(world.turn().call(LABELS, mailbox=ADDRESS), "needs_reconnect")
    assert world.fake.calls("gmail") == []


def test_labels_answers_unreachable_when_gmail_is_down(world: World) -> None:
    world.connect()
    world.fake.gmail_down = True
    failed(world.turn().call(LABELS, mailbox=ADDRESS), "unreachable")


def test_an_absent_key_marker_is_never_a_real_value() -> None:
    assert dig({"a": [{"b": 1}]}, "b") == 1 and dig({"a": 1}, "b") == ABSENT
