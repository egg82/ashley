"""The Discord bot answering messages as they arrive: one reply per message however often it is delivered or by how many
sessions, who is answered, the reply split in order with `reply_to` only in a channel, the failure lines, a failed send
stopping that reply, typing while she thinks, and nothing stopping the next message."""

import asyncio
from collections.abc import Generator

import pytest
from ashley.channels.discord.bot import Bot
from ashley.channels.discord.message import Message
from ashley.channels.model import Device, DiscordServer, Inbound
from ashley.channels.respond import RespondRefused, RespondUnavailable
from ashley.people.people import PeopleUnavailable
from contract.conversations_support import run
from discord_support import (ALANA, ALANA_ID, CHANNEL, DM_CHANNEL, GUEST_ID, NOW, OTHER_GUILD, SIDE_CHANNEL,
                             STRANGER_GUILD, FakeConnect, FakeDiscord, Sent,
                              failed, message, quiet, rig, running, snowflake, unwire, until)

DM = {"guild_id": None, "channel_id": DM_CHANNEL, "mentions_me": False}
PARAGRAPHS = "\n\n".join(c * 1500 for c in "abc")


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    yield
    unwire()


def test_a_mention_gets_one_reply_to_it_and_the_claim_is_recorded() -> None:
    r = rig()
    sent = message(content="<@4242> hello there")

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert r.replies.inbounds == [Inbound(1, f"discord:{CHANNEL}", "hello there", "chat", "text", "household",
                                          ALANA.id, False, None, "discord", later=True, source=f"discord:{sent.id}", discord_channel=CHANNEL)]
    assert r.discord.sends == [Sent(CHANNEL, "hi back", sent.id)]
    assert r.seen.claims == {sent.id: (CHANNEL, NOW)}
    assert r.people.asked == [("discord", str(ALANA_ID))]


def test_a_reply_to_one_of_hers_is_answered_without_a_mention() -> None:
    r = rig()
    sent = message(mentions_me=False, replies_to_me=True)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)

    run(scenario())
    assert [s.reply_to for s in r.discord.sends] == [sent.id]


def test_one_message_delivered_twice_is_answered_once() -> None:
    r = rig()
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)
            r.discord.incoming.put_nowait(sent)     # and again after the first reply is long done
            await quiet()

    run(scenario())
    assert len(r.replies.inbounds) == 1 and len(r.discord.sends) == 1


def test_two_sessions_sharing_the_claim_store_answer_a_message_once_between_them() -> None:
    first, second = rig(), rig()
    other = FakeDiscord()
    twin = Bot(FakeConnect(other), first.seen, first.config, respond=second.replies, now=lambda: NOW)
    sent = message()

    async def scenario() -> None:
        async with running(first):
            task = asyncio.create_task(twin.run())
            first.discord.incoming.put_nowait(sent)
            other.incoming.put_nowait(sent)
            await until(lambda: first.discord.sends or other.sends)
            await quiet()
            other.incoming.put_nowait(None)
            await task

    run(scenario())
    assert len(first.discord.sends) + len(other.sends) == 1
    assert len(first.replies.inbounds) + len(second.replies.inbounds) == 1


def test_a_reply_to_a_channel_message_replies_to_it_only_in_its_first_chunk() -> None:
    r = rig()
    r.replies.body = PARAGRAPHS
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: len(r.discord.sends) == 3)

    run(scenario())
    assert r.discord.sends == [Sent(CHANNEL, "a" * 1500, sent.id), Sent(CHANNEL, "b" * 1500, None),
                               Sent(CHANNEL, "c" * 1500, None)]


def test_a_message_in_another_channel_of_the_server_is_answered_there_in_its_own_thread() -> None:
    r = rig()
    side = message(channel_id=SIDE_CHANNEL)
    home = message(id=snowflake(NOW) + 1)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(side)
            r.discord.incoming.put_nowait(home)
            await until(lambda: len(r.discord.sends) == 2)

    run(scenario())
    assert r.discord.sends == [Sent(SIDE_CHANNEL, "hi back", side.id), Sent(CHANNEL, "hi back", home.id)]
    assert [i.thread for i in r.replies.inbounds] == [f"discord:{SIDE_CHANNEL}", f"discord:{CHANNEL}"]
    assert set(r.discord.typed) <= {SIDE_CHANNEL, CHANNEL}


def test_a_message_in_a_server_that_is_not_a_device_is_ignored_and_a_server_added_later_is_answered() -> None:
    r = rig()
    other = Device(8, 2, "kitchen", "kitchen", "household", "text", "chat")
    early = message(id=snowflake(NOW) + 1, guild_id=OTHER_GUILD, channel_id=SIDE_CHANNEL)
    late = message(id=snowflake(NOW) + 2, guild_id=OTHER_GUILD, channel_id=SIDE_CHANNEL)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(early)
            await quiet()
            assert r.discord.sends == [] and r.replies.inbounds == []
            r.devices.servers.append(DiscordServer(other, OTHER_GUILD, SIDE_CHANNEL))
            r.discord.incoming.put_nowait(late)
            await until(lambda: r.discord.sends)

    run(scenario())
    assert r.discord.sends == [Sent(SIDE_CHANNEL, "hi back", late.id)]
    assert [i.household_id for i in r.replies.inbounds] == [2]


def test_a_dm_reply_is_never_a_reply_to() -> None:
    r = rig()
    r.replies.body = PARAGRAPHS
    sent = message(author_id=ALANA_ID, **DM)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: len(r.discord.sends) == 3)

    run(scenario())
    assert [(s.channel_id, s.reply_to) for s in r.discord.sends] == [(DM_CHANNEL, None)] * 3
    [inbound] = r.replies.inbounds
    assert (inbound.audience, inbound.speaker_id, inbound.thread) == ("owner", ALANA.id, f"discord:{DM_CHANNEL}")


def test_a_long_reply_is_cut_to_2000_characters_and_to_max_messages_ending_with_an_ellipsis() -> None:
    r = rig(max_messages=2)
    r.replies.body = "x" * 4500

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(message())
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    texts = r.discord.texts()
    assert len(texts) == 2 and texts[0] == "x" * 2000
    assert len(texts[1]) <= 2000 and texts[1].endswith("…")


@pytest.mark.parametrize(("error", "line"), [
    (RespondUnavailable("down"), "I cannot answer right now."),
    (RespondRefused("no"), "I would rather not."),
])
@pytest.mark.parametrize("dm", [False, True])
def test_a_respond_failure_posts_its_configured_line_and_nothing_else(error: Exception, line: str, dm: bool) -> None:
    r = rig()
    r.replies.error = error
    sent = message(**DM) if dm else message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert r.discord.sends == [Sent(DM_CHANNEL if dm else CHANNEL, line, None if dm else sent.id)]


def test_a_failed_send_stops_the_rest_of_that_reply_but_not_the_next_message() -> None:
    r = rig()
    r.replies.body = PARAGRAPHS
    r.discord.send_errors = {1: failed(403)}
    first, second = message(), message(id=snowflake(NOW) + 1)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(first)
            await until(lambda: len(r.discord.sends) == 2)
            await quiet()
            assert len(r.discord.sends) == 2, "the third chunk is not sent after the second failed"
            r.discord.incoming.put_nowait(second)
            await until(lambda: len(r.discord.sends) > 2)

    run(scenario())
    assert r.discord.sends[2] == Sent(CHANNEL, "a" * 1500, second.id), "the next message was answered from its start"


def test_a_typing_failure_does_not_stop_the_reply() -> None:
    r = rig()
    r.discord.typing_error = failed(429)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(message())
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert r.discord.texts() == ["hi back"]


def test_she_shows_typing_until_the_reply_is_sent_and_then_stops() -> None:
    r = rig()
    r.replies.blocking = {"hello"}
    counted: list[int] = []

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(message())
            await until(lambda: len(r.discord.typed) >= 3)      # refreshed, not shown once
            assert r.discord.sends == [], "no reply while she is still thinking"
            r.replies.gate.set()
            await until(lambda: r.discord.sends)
            counted.append(len(r.discord.typed))
            await quiet()

    run(scenario())
    assert set(r.discord.typed) == {CHANNEL}
    assert len(r.discord.typed) <= counted[0] + 1, "typing stops once the reply is sent"


def test_each_message_is_handled_in_its_own_task_so_a_slow_one_does_not_hold_the_next() -> None:
    r = rig()
    r.replies.blocking = {"slow"}
    slow, fast = message(content="slow"), message(id=snowflake(NOW) + 1, content="fast")

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(slow)
            r.discord.incoming.put_nowait(fast)
            await until(lambda: r.discord.sends)
            assert r.discord.sends == [Sent(CHANNEL, "hi back", fast.id)]
            r.replies.gate.set()
            await until(lambda: len(r.discord.sends) == 2)

    run(scenario())
    assert r.discord.sends[1].reply_to == slow.id


@pytest.mark.parametrize("sent", [
    message(author_is_bot=True),
    message(mentions_me=False),
    message(guild_id=STRANGER_GUILD),
    message(content="<@4242>"),
    message(author_id=GUEST_ID, **DM),
])
def test_what_route_declines_is_neither_claimed_nor_answered_and_the_next_message_still_is(sent: Message) -> None:
    r = rig()
    wanted = message(id=snowflake(NOW) + 9)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            r.discord.incoming.put_nowait(wanted)
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert list(r.seen.claims) == [wanted.id]
    assert r.discord.sends == [Sent(CHANNEL, "hi back", wanted.id)]


def test_a_message_already_claimed_is_dropped_without_a_model_call() -> None:
    r = rig()
    sent = message()
    r.seen.preclaim(sent.id, CHANNEL, NOW)

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await quiet()

    run(scenario())
    assert r.replies.inbounds == [] and r.discord.sends == []


def test_an_unwritable_claim_store_means_no_reply_for_now() -> None:
    r = rig()
    r.seen.unavailable = True
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await quiet()
            r.seen.unavailable = False
            r.discord.incoming.put_nowait(message(id=snowflake(NOW) + 1))
            await until(lambda: r.discord.sends)

    run(scenario())
    assert r.replies.inbounds[0].text == "hello" and len(r.replies.inbounds) == 1, "only the later message"
    assert sent.id not in r.seen.claims


def test_people_being_unavailable_drops_the_message_unclaimed_and_the_next_is_answered() -> None:
    r = rig()
    r.people.error = PeopleUnavailable("down")
    dropped = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(dropped)
            await quiet()
            assert r.discord.sends == [] and r.replies.inbounds == []
            r.people.error = None
            r.discord.incoming.put_nowait(message(id=snowflake(NOW) + 1))
            await until(lambda: r.discord.sends)

    run(scenario())
    assert dropped.id not in r.seen.claims, "a dropped message may be answered when it is seen again"

