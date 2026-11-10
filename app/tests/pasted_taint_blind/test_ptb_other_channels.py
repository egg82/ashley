"""Discord carries a forward (a structured field of the message) as the turn's block, never wording; voice cannot paste,
whatever length it hears."""

from dataclasses import replace

from ashley.channels.discord.route import route
from ashley.channels.model import DiscordServer
from discord_support import ALANA, CHANNEL, DM_CHANNEL, FAMILY, GUILD, ME, message
from pasted_taint_blind_support import DISCORD_FIELD, ORIGIN, TYPED_A, inbound, over, person_turn, read, spans_of, under
from test_voice_run import FakeSpeech, FakeTurnLoop, carry, household, satellite_row, db_url as db_url

SERVERS = {GUILD: DiscordServer(FAMILY, GUILD, CHANNEL)}
TYPED = "what do you make of this?"


def test_a_forward_over_the_threshold_is_the_block_and_taints_the_turn_pasted() -> None:
    got = route(replace(message(content=f"<@{ME}> {TYPED}"), **{DISCORD_FIELD: over()}), ME, SERVERS, ALANA)
    assert got is not None and got.taint == ORIGIN
    [block] = spans_of(got)
    assert block.text.strip() == over().strip() and got.text == TYPED
    assert TYPED not in block.text and "PASTE-9f2c7a" not in got.text


def test_the_forward_is_cut_from_words_and_the_typed_ask_stays() -> None:
    got = route(replace(message(content=f"<@{ME}> {TYPED}"), **{DISCORD_FIELD: over()}), ME, SERVERS, ALANA)
    assert got is not None
    words = read(inbound(taint=ORIGIN), person_turn(1, got.text, spans_of(got)))
    assert words and TYPED in words[0] and not any("PASTE-9f2c7a" in w for w in words)


def test_a_forward_under_the_threshold_does_not_taint() -> None:
    got = route(replace(message(content=f"<@{ME}> {TYPED}"), **{DISCORD_FIELD: under()}), ME, SERVERS, ALANA)
    assert got is not None and got.taint is None and len(spans_of(got)) == 1
    assert read(inbound(), person_turn(1, got.text, spans_of(got))) == (got.text,)


def test_long_text_that_looks_quoted_but_names_no_forward_has_no_block() -> None:
    looks = f"<@{ME}> {TYPED}\n> {over()}\n-----Original Message-----\n{over()}"
    got = route(message(content=looks), ME, SERVERS, ALANA)
    assert got is not None and got.taint is None and spans_of(got) == ()


def test_a_long_reply_to_her_is_not_a_quote() -> None:
    got = route(message(content=f"<@{ME}> {TYPED} {over()}", mentions_me=False, replies_to_me=True), ME, SERVERS, ALANA)
    assert got is not None and got.taint is None and spans_of(got) == ()


def test_a_dm_forward_taints_the_same() -> None:
    got = route(replace(message(content=TYPED, guild_id=None, channel_id=DM_CHANNEL, mentions_me=False),
                        **{DISCORD_FIELD: over()}), ME, SERVERS, ALANA)
    assert got is not None and got.taint == ORIGIN and len(spans_of(got)) == 1


def test_voice_is_never_marked_however_long_it_hears(db_url: str) -> None:
    satellite = satellite_row(db_url, household(db_url))
    loop = FakeTurnLoop()
    carry(db_url, satellite, FakeSpeech(transcript=TYPED_A + over()), loop)
    [heard] = loop.asked
    assert heard.channel == "voice" and heard.taint is None and spans_of(heard) == ()
