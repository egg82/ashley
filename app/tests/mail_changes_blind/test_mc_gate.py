"""The gate by resource for changes (design's table: a kept mailbox is changed only where the reply reaches its owner alone
and the speaker is the owner; a shared one where the channel names the speaker, a member of the household), and a
connection that must be connected again (design: "her tools over it answer `needs_reconnect`")."""

from typing import Any

import pytest
from ashley.tools import outside_config
from mail_changes_blind_support import (ADDRESS, CHANGES, DRAFT, LABEL, M1, SEARCH, SEED_ACCESS, SEND, World, data,
                                        failed, label_args, labels_now, send_args, untouched)

CALLS = {DRAFT: send_args(), SEND: send_args(), LABEL: label_args(M1, add_labels=["School"])}
KEPT_CHANNELS = [
    {"audience": "household", "shared": True},
    {"audience": "present", "shared": True},
    {"audience": "present", "shared": False},
    {"audience": "owner", "shared": True},
    {"audience": "owner", "shared": False, "device_id": 7},
    {"speaker": False},
]
KEPT_IDS = ["household-channel", "satellite", "present-room", "owner-on-shared", "owner-with-screen", "no-speaker"]


@pytest.mark.parametrize("channel", KEPT_CHANNELS, ids=KEPT_IDS)
def test_a_kept_mailbox_is_changed_on_no_channel_others_can_read(stocked: World, channel: dict[str, Any]) -> None:
    before = labels_now(stocked)
    turn = stocked.turn(**channel)
    for tool, args in CALLS.items():
        failed(turn.send(tool, args))
    assert stocked.fake.calls("gmail") == []
    untouched(stocked, before)
    assert not stocked.turn().send(SEND, CALLS[SEND]).is_error  # control: its owner alone sends from it
    assert len(stocked.fake.sent) == 1


def test_a_housemate_cannot_change_a_kept_mailbox_from_their_own_chat(stocked: World) -> None:
    before = labels_now(stocked)
    turn = stocked.turn("sam")
    for tool, args in CALLS.items():
        failed(turn.send(tool, args))
    assert stocked.fake.calls("gmail") == []
    untouched(stocked, before)
    assert not stocked.turn().send(SEND, CALLS[SEND]).is_error  # control: its owner sends from it


def test_a_shared_mailbox_is_changed_by_a_housemate_with_its_owners_login(stocked: World) -> None:
    stocked.share(stocked.connection)
    turn = stocked.turn("sam")
    assert not turn.send(SEND, CALLS[SEND]).is_error
    assert not turn.send(DRAFT, CALLS[DRAFT]).is_error
    assert not turn.send(LABEL, CALLS[LABEL]).is_error
    assert len(stocked.fake.sent) == 1 and len(stocked.fake.drafts) == 1 and "Label_12" in stocked.fake.labels_of("m1")
    assert set(stocked.fake.bearers()) == {SEED_ACCESS}


def test_a_shared_channel_that_names_a_member_changes_a_shared_mailbox(stocked: World) -> None:
    stocked.share(stocked.connection)
    assert not stocked.turn("sam", audience="household", shared=True).send(SEND, CALLS[SEND]).is_error
    assert len(stocked.fake.sent) == 1


@pytest.mark.parametrize("channel", [{"audience": "present", "shared": True, "speaker": False}, {"speaker": False},
                                     {"audience": "present", "shared": True, "speaker": False, "heard_as": 1}],
                         ids=["satellite", "no-speaker", "voice-match"])
def test_a_shared_mailbox_is_read_but_never_changed_where_nobody_is_named(stocked: World, channel: dict[str, Any]) -> None:
    stocked.share(stocked.connection)
    before = labels_now(stocked)
    turn = stocked.turn(**channel)
    assert data(turn.call(SEARCH, mailbox=ADDRESS))  # control: it is read aloud
    for tool, args in CALLS.items():
        failed(turn.send(tool, args))
    untouched(stocked, before)
    assert not stocked.turn("sam").send(SEND, CALLS[SEND]).is_error  # control: a named member sends from it


def test_a_held_change_is_not_made_on_a_channel_where_agreement_cannot_follow(stocked: World) -> None:
    stocked.share(stocked.connection)
    turn = stocked.guarded("sam", audience="household", shared=True)
    assert not turn.call(SEARCH, mailbox=ADDRESS).is_error and turn.tainted == SEARCH
    got = turn.send(SEND, CALLS[SEND])
    assert got.is_error and got.content == outside_config.load().needs_private
    assert stocked.fake.sent == [] and turn.pending() == ""


@pytest.mark.parametrize("tool", CHANGES)
def test_a_connection_that_must_be_connected_again_answers_needs_reconnect_and_changes_nothing(stocked: World, tool: str) -> None:
    stocked.mark_reconnect(stocked.connection)
    before = labels_now(stocked)
    failed(stocked.turn().send(tool, CALLS[tool]), "needs_reconnect")
    untouched(stocked, before)
