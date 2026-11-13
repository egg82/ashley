"""`route` (pure) turns a Discord message into the `Inbound` she answers, or None; `sent_at` reads a snowflake's time.

DMs belong to the mapped person; household-channel messages need a mention or a reply to her and take the channel
device's settings; bots, unmapped DMs, unknown servers and unaddressed or empty messages are not answered."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashley.channels.discord.message import sent_at
from ashley.channels.discord.route import route
from ashley.channels.model import Device, DiscordServer, Inbound
from ashley.people.model import Person
from discord_support import (ALANA, CHANNEL, DM_CHANNEL, FAMILY, GUILD, ME, OTHER_CHANNEL, OTHER_GUILD, SIDE_CHANNEL,
                             STRANGER_GUILD, message, snowflake)
from hypothesis import given
from hypothesis import strategies as st

SERVERS = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)}
DM = {"guild_id": None, "channel_id": DM_CHANNEL, "mentions_me": False}


def inbound(**changes: object) -> Inbound:
    """What the household channel yields for Alana's "hello"."""
    base = Inbound(household_id=1, thread=f"discord:{CHANNEL}", text="hello", kind="chat", medium="text",
                   audience="household", speaker_id=ALANA.id, shared=False, place=None, channel="discord", remembers=True, later=True,
                   source=f"discord:{message().id}", discord_channel=CHANNEL)
    return replace(base, **changes)


def test_a_mention_in_the_household_channel_is_an_inbound_from_the_device_and_the_person() -> None:
    assert route(message(), ME, SERVERS, ALANA) == inbound()


def test_a_reply_to_her_needs_no_mention() -> None:
    assert route(message(mentions_me=False, replies_to_me=True), ME, SERVERS, ALANA) == inbound()


def test_a_message_that_neither_mentions_nor_replies_to_her_is_not_answered() -> None:
    assert route(message(mentions_me=False, replies_to_me=False), ME, SERVERS, ALANA) is None
    assert route(message(), ME, SERVERS, ALANA) is not None, "control: the same message with the mention is"


def test_a_name_in_the_text_is_not_an_address() -> None:
    assert route(message(content="hey ashley, are you there?", mentions_me=False), ME, SERVERS, ALANA) is None


def test_a_server_that_is_not_a_registered_device_is_ignored_even_when_she_is_mentioned() -> None:
    assert route(message(guild_id=STRANGER_GUILD), ME, SERVERS, ALANA) is None
    assert route(message(), ME, {}, ALANA) is None
    assert route(message(guild_id=STRANGER_GUILD, channel_id=CHANNEL), ME, SERVERS, ALANA) is None, "even in its id"


def test_any_channel_of_a_registered_server_is_answered_when_addressed_not_only_the_home_channel() -> None:
    got = route(message(channel_id=SIDE_CHANNEL), ME, SERVERS, ALANA)
    assert got == inbound(thread=f"discord:{SIDE_CHANNEL}", discord_channel=SIDE_CHANNEL)
    assert route(message(channel_id=SIDE_CHANNEL, mentions_me=False), ME, SERVERS, ALANA) is None, "still needs an address"


def test_each_channel_is_its_own_thread_and_the_server_gives_the_settings() -> None:
    threads = {c: route(message(channel_id=c), ME, SERVERS, ALANA) for c in (CHANNEL, SIDE_CHANNEL, SIDE_CHANNEL + 1)}
    assert [t.thread for t in threads.values() if t is not None] == [f"discord:{c}" for c in threads]
    assert {replace(t, thread="", discord_channel=CHANNEL) for t in threads.values() if t is not None} == {inbound(thread="")}
    assert [t.discord_channel for t in threads.values() if t is not None] == list(threads)


def test_a_servers_device_is_found_by_guild_whichever_channel_the_ids_collide_with() -> None:
    other = Device(9, 3, "other house", "den", "household", "text", "chat")
    both = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL), OTHER_GUILD: DiscordServer(other, OTHER_GUILD, OTHER_CHANNEL)}
    assert route(message(guild_id=OTHER_GUILD, channel_id=CHANNEL), ME, both, None) == inbound(
        household_id=3, thread=f"discord:{CHANNEL}", speaker_id=None, taint="stranger", discord_channel=CHANNEL)
    assert route(message(guild_id=GUILD, channel_id=OTHER_CHANNEL), ME, both, ALANA) == inbound(
        thread=f"discord:{OTHER_CHANNEL}", discord_channel=OTHER_CHANNEL)


def test_household_kind_medium_audience_and_remembers_come_from_the_servers_device() -> None:
    quiet = Device(9, 3, "guest room", "guest room", "present", "spoken", "brainstorm", remembers=False)
    got = route(message(), ME, {GUILD: DiscordServer(quiet, GUILD, CHANNEL)}, None)
    assert got == inbound(household_id=3, kind="brainstorm", medium="spoken", audience="present", speaker_id=None,
                          remembers=False, taint="stranger")


def test_the_thread_names_the_channel_and_a_channel_never_shares_a_place_or_presence() -> None:
    got = route(message(), ME, SERVERS, ALANA)
    assert got is not None
    assert got.thread == f"discord:{CHANNEL}" and got.place is None and got.shared is False
    assert FAMILY.place != "", "control: the device has a place that must not leak into the inbound"


@pytest.mark.parametrize(("person", "speaker"), [
    (ALANA, ALANA.id),
    (Person(6, 1, "Sam"), 6),
    (Person(8, 2, "Visitor"), None),    # mapped, but in another household than the channel's device
    (None, None),                        # nobody mapped: answered as an unknown speaker
])
def test_the_speaker_is_the_person_only_when_they_are_in_the_devices_household(
        person: Person | None, speaker: int | None) -> None:
    got = route(message(), ME, SERVERS, person)
    assert got is not None and got.speaker_id == speaker
    assert got.household_id == FAMILY.household_id, "the household is the device's, whoever wrote"


@pytest.mark.parametrize("content", ["<@4242> hello", "<@!4242> hello", "hello <@4242>", "hello <@!4242>",
                                     "  <@4242>  <@!4242>  hello  ", "\n<@4242>\nhello\n"])
def test_her_own_mention_tokens_are_removed_and_the_text_stripped(content: str) -> None:
    got = route(message(content=content), ME, SERVERS, ALANA)
    assert got is not None and got.text == "hello"


def test_other_peoples_mentions_and_ids_that_merely_start_with_hers_stay() -> None:
    got = route(message(content="<@999> and <@42420> hi <@4242>"), ME, SERVERS, ALANA)
    assert got is not None and got.text == "<@999> and <@42420> hi"
    got = route(message(content="<@42421> hi", mentions_me=False, replies_to_me=True), ME, SERVERS, ALANA)
    assert got is not None and got.text == "<@42421> hi"


def test_the_text_keeps_its_inner_spelling() -> None:
    got = route(message(content="  Turn ON the Lights\n\nplease  "), ME, SERVERS, ALANA)
    assert got is not None and got.text == "Turn ON the Lights\n\nplease"


@pytest.mark.parametrize("content", ["", "   ", "\n\t", "<@4242>", "<@!4242>", " <@4242> <@!4242> \n"])
def test_nothing_left_after_the_mention_and_whitespace_is_not_answered(content: str) -> None:
    assert route(message(content=content), ME, SERVERS, ALANA) is None
    assert route(message(content=content, **DM), ME, SERVERS, ALANA) is None


@pytest.mark.parametrize("fields", [{}, DM, {"mentions_me": False, "replies_to_me": True}])
def test_a_bot_author_is_never_answered(fields: dict[str, object]) -> None:
    assert route(message(author_is_bot=True, **fields), ME, SERVERS, ALANA) is None
    assert route(message(author_is_bot=False, **fields), ME, SERVERS, ALANA) is not None, "control: a person is"


def test_a_dm_from_a_mapped_account_is_that_persons_owner_chat() -> None:
    got = route(message(content="what's for dinner?", **DM), ME, SERVERS, Person(5, 2, "Alana"))
    assert got == Inbound(household_id=2, thread=f"discord:{DM_CHANNEL}", text="what's for dinner?", kind="chat",
                          medium="text", audience="owner", speaker_id=5, shared=False, place=None, channel="discord",
                          remembers=True, later=True, source=f"discord:{message().id}")


def test_a_dm_from_an_unmapped_account_is_not_answered() -> None:
    assert route(message(**DM), ME, SERVERS, None) is None


def test_a_dm_needs_no_mention_and_its_text_is_stripped_of_hers() -> None:
    got = route(message(content=" <@4242> hi ", **DM), ME, SERVERS, ALANA)
    assert got is not None and got.text == "hi"


def test_a_dm_in_a_channel_id_that_is_also_registered_is_still_the_persons() -> None:
    got = route(message(channel_id=CHANNEL, guild_id=None), ME, SERVERS, ALANA)
    assert got is not None and got.audience == "owner"


@given(content=st.text(max_size=60), mentions=st.booleans(), replies=st.booleans(), guild=st.booleans(),
       bot=st.booleans(), mapped=st.booleans())
def test_whatever_arrives_the_text_is_non_empty_stripped_and_free_of_her_tokens(
        content: str, mentions: bool, replies: bool, guild: bool, bot: bool, mapped: bool) -> None:
    sent = message(content=content, mentions_me=mentions, replies_to_me=replies, author_is_bot=bot,
                   guild_id=GUILD if guild else None, channel_id=CHANNEL if guild else DM_CHANNEL)
    got = route(sent, ME, SERVERS, ALANA if mapped else None)
    if got is None:
        return
    assert not bot
    assert got.text != "" and got.text == got.text.strip()
    assert "<@4242>" not in got.text and "<@!4242>" not in got.text
    assert got.shared is False and got.place is None
    assert got.thread == f"discord:{sent.channel_id}"
    assert (guild and (mentions or replies)) or (not guild and mapped)


def test_a_snowflake_is_the_time_it_was_made() -> None:
    assert sent_at(175928847299117063) == datetime(2016, 4, 30, 11, 18, 25, 796000, tzinfo=UTC)
    assert sent_at(0) == datetime(2015, 1, 1, tzinfo=UTC)


def test_sent_at_is_timezone_aware_utc_and_ignores_the_low_22_bits() -> None:
    made = datetime(2026, 10, 26, 12, 0, 0, 250000, tzinfo=UTC)
    assert sent_at(snowflake(made)) == made
    assert sent_at(snowflake(made, sequence=(1 << 22) - 1)) == made
    assert sent_at(snowflake(made)).utcoffset() is not None
    assert sent_at(snowflake(made) + (1 << 22)) - made == timedelta(milliseconds=1)


@given(ms=st.integers(0, 4_000_000_000_000), sequence=st.integers(0, (1 << 22) - 1))
def test_sent_at_inverts_the_snowflake_layout(ms: int, sequence: int) -> None:
    flake = (ms << 22) | sequence
    assert sent_at(flake) == datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms + 1_420_070_400_000)


def test_a_message_with_a_nul_is_not_answered() -> None:
    assert route(message(content="a\u0000b"), ME, SERVERS, ALANA) is None
    assert route(message(content="a\u0000b", **DM), ME, SERVERS, ALANA) is None
