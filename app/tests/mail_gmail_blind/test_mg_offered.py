"""Which turns are offered the mail tools, and what each tool's spec says (design: "The gate is by resource", "Personal
connections only, so the gate is `owner_alone`", the tools table, "A tool needing a Google scope the connection was not
granted is not offered")."""

from typing import Any

import pytest
from mail_gmail_blind_support import (ADDRESS, BASE_SCOPES, BOXES, GMAIL_SCOPE, LABELS, MAIL_TOOLS, READ, SEARCH, World,
                                      failed)


def test_the_owner_alone_is_offered_all_four(world: World) -> None:
    world.connect()
    assert set(MAIL_TOOLS) <= world.turn().names()


def test_every_tool_reads_and_the_two_that_show_strangers_words_are_outside(world: World) -> None:
    world.connect()
    specs = world.turn().specs()
    assert all(specs[n].reads is True for n in MAIL_TOOLS)
    assert specs[SEARCH].outside is True and specs[READ].outside is True
    assert specs[BOXES].outside is False and specs[LABELS].outside is False


@pytest.mark.parametrize("channel", [
    {"audience": "household", "shared": True},
    {"audience": "present", "shared": True},
    {"audience": "present", "shared": False},
    {"audience": "household", "shared": False},
    {"audience": "owner", "shared": True},
    {"audience": "owner", "shared": False, "device_id": 7},
], ids=["household-channel", "satellite", "present-room", "household-audience", "owner-on-shared", "owner-with-screen"])
def test_a_channel_others_can_read_is_offered_none(world: World, channel: dict[str, Any]) -> None:
    world.connect()
    assert set(MAIL_TOOLS) <= world.turn().names()  # control: the same connection is offered to its owner
    turn = world.turn(**channel)
    assert not set(MAIL_TOOLS) & turn.names()
    for name in MAIL_TOOLS:
        assert turn.call(name, mailbox=ADDRESS).is_error
    assert world.fake.calls("gmail") == []


def test_an_unknown_speaker_is_offered_none(world: World) -> None:
    world.connect()
    assert set(MAIL_TOOLS) <= world.turn().names()  # control: the same connection is offered to its owner
    turn = world.turn(speaker=False)
    assert not set(MAIL_TOOLS) & turn.names()
    assert turn.call(SEARCH, mailbox=ADDRESS).is_error
    assert world.fake.calls("gmail") == []


def test_a_voice_match_never_makes_someone_the_speaker(world: World) -> None:
    world.connect()
    assert set(MAIL_TOOLS) <= world.turn().names()  # control: the same connection is offered to its owner
    turn = world.turn(speaker=False, audience="present", shared=True, heard_as=world.alana)
    assert not set(MAIL_TOOLS) & turn.names()
    assert world.fake.calls("gmail") == []


def test_a_housemate_has_no_access_to_anothers_login(world: World) -> None:
    world.connect("alana")
    assert set(MAIL_TOOLS) <= world.turn().names()  # control: the same connection is offered to its owner
    sam = world.turn("sam")
    assert not set(MAIL_TOOLS) & sam.names()
    assert sam.call(SEARCH, mailbox=ADDRESS).is_error
    assert world.fake.calls("gmail") == []


def test_each_person_reaches_only_their_own_mailbox(world: World) -> None:
    world.connect("alana")
    world.fake.accept("at-sam-0002-ACCESSTOKEN", "rt-sam-0002-REFRESHTOKEN")
    world.connect("sam", access="at-sam-0002-ACCESSTOKEN", refresh="rt-sam-0002-REFRESHTOKEN")
    assert set(MAIL_TOOLS) <= world.turn("sam").names()
    sam_boxes = world.turn("sam").call(BOXES)
    assert ADDRESS in sam_boxes.content
    assert not world.turn("sam").call(SEARCH, mailbox=ADDRESS).is_error
    assert set(world.fake.bearers()) == {"at-sam-0002-ACCESSTOKEN"}


def test_a_person_of_another_household_cannot_use_it(world: World) -> None:
    world.connect("alana")
    assert set(MAIL_TOOLS) <= world.turn().names()  # control: the same connection is offered to its owner
    assert not set(MAIL_TOOLS) & world.turn("kim").names()


def test_a_connection_not_granted_a_gmail_scope_offers_no_mail_tool(world: World) -> None:
    world.connect(scopes=BASE_SCOPES)
    turn = world.turn()
    assert not set(MAIL_TOOLS) & turn.names()
    assert turn.call(SEARCH, mailbox=ADDRESS).is_error
    assert world.fake.calls("gmail") == []


def test_a_connection_granted_the_scope_by_its_short_name_is_offered(world: World) -> None:
    world.connect(scopes=(*BASE_SCOPES, GMAIL_SCOPE.rsplit("/", 1)[-1]))
    assert set(MAIL_TOOLS) <= world.turn().names()


def test_no_mail_connection_offers_no_tool_and_a_call_answers_an_error_without_reaching_gmail(world: World) -> None:
    turn = world.turn()
    assert not set(MAIL_TOOLS) & turn.names()
    for name in MAIL_TOOLS:
        assert turn.call(name, mailbox=ADDRESS).is_error
    assert world.fake.seen == []


def test_connections_that_cannot_be_opened_offer_no_mail_tool(unkeyed: World) -> None:
    assert not set(MAIL_TOOLS) & unkeyed.turn().names()
    assert unkeyed.fake.seen == []


def test_a_reads_only_turn_keeps_the_mail_tools_for_the_owner_and_drops_them_elsewhere(world: World) -> None:
    world.connect()
    assert set(MAIL_TOOLS) <= world.turn(reads_only=True).names()
    assert not set(MAIL_TOOLS) & world.turn(reads_only=True, audience="household", shared=True).names()


def test_a_connection_that_needs_a_reconnect_still_offers_the_tools_so_she_can_say_so(world: World) -> None:
    world.mark_reconnect(world.connect())
    turn = world.turn()
    assert set(MAIL_TOOLS) <= turn.names()
    failed(turn.call(SEARCH, mailbox=ADDRESS), "needs_reconnect")
