"""The bot's session: failover catch-up (which channels, from which message, within which window, one failure not
stopping the rest), pruning old claims, the session closing on cancellation or when the stream ends, DevicesUnavailable
propagating, and the log lines carrying ids and counts but never message content."""

import asyncio
from collections.abc import Generator
from datetime import timedelta

import pytest
from ashley import logs
from ashley.channels.devices import DevicesUnavailable
from ashley.channels.discord.message import Message, sent_at
from ashley.channels.model import Device, DiscordServer
from ashley.channels.respond import RespondRefused
from ashley.people.people import PeopleUnavailable
from contract.conversations_support import events, run
from discord_support import (ALANA_ID, CHANNEL, DM_CHANNEL, FAMILY, GUEST_ID, GUILD, NOW, OTHER_CHANNEL, OTHER_GUILD,
                             SECRET, SIDE_CHANNEL, STRANGER_GUILD, Rig, Sent, ago, failed, message, quiet, rig, running, snowflake, unwire, until)

DM = {"guild_id": None, "channel_id": DM_CHANNEL, "mentions_me": False}
SECOND = Device(8, 1, "kitchen", "kitchen", "household", "text", "chat")


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    yield
    unwire()


def at(seconds_ago: float, **changes: object) -> Message:
    """A message sent `seconds_ago` before NOW."""
    return message(**{"id": snowflake(ago(seconds_ago)), **changes})


def asked(r: Rig) -> dict[int, int]:
    return {channel: after for channel, after, _ in r.discord.asked}


def test_catch_up_asks_each_servers_home_channel_from_the_window_start_when_nothing_was_claimed() -> None:
    r = rig([DiscordServer(FAMILY, GUILD, CHANNEL), DiscordServer(SECOND, OTHER_GUILD, OTHER_CHANNEL)])

    async def scenario() -> None:
        async with running(r):
            await until(lambda: len(r.discord.asked) == 2)

    run(scenario())
    assert set(asked(r)) == {CHANNEL, OTHER_CHANNEL}
    assert {sent_at(after) for after in asked(r).values()} == {ago(600)}
    assert r.seen.last_asked == [ago(600)]


def test_catch_up_resumes_after_the_last_claimed_message_in_a_channel_and_covers_known_dm_channels() -> None:
    r = rig()
    claimed_in_channel, claimed_in_dm = snowflake(ago(200)), snowflake(ago(60))
    r.seen.preclaim(claimed_in_channel - 5, CHANNEL, ago(250))
    r.seen.preclaim(claimed_in_channel, CHANNEL, ago(200))
    r.seen.preclaim(claimed_in_dm, DM_CHANNEL, ago(60))
    r.seen.preclaim(snowflake(ago(5000)), 3003, ago(5000))      # a DM channel last heard from long ago
    r.discord.backlog[DM_CHANNEL] = [at(30, author_id=ALANA_ID, **DM)]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)

    run(scenario())
    assert asked(r) == {CHANNEL: claimed_in_channel, DM_CHANNEL: claimed_in_dm}, "and not the long-silent channel"
    assert [s.channel_id for s in r.discord.sends] == [DM_CHANNEL]


def test_catch_up_reads_only_the_home_channel_of_a_server_unless_she_answered_in_another_channel_lately() -> None:
    r = rig()
    r.discord.backlog[SIDE_CHANNEL] = [at(100, channel_id=SIDE_CHANNEL)]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.asked)
            await quiet()

    run(scenario())
    assert set(asked(r)) == {CHANNEL}, "the other channels of the server are not swept"
    assert r.discord.sends == []

    r = rig()
    claimed = snowflake(ago(200))
    r.seen.preclaim(claimed, SIDE_CHANNEL, ago(200))
    r.discord.backlog[SIDE_CHANNEL] = [at(100, channel_id=SIDE_CHANNEL)]

    async def known() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)

    run(known())
    assert asked(r) == {CHANNEL: asked(r)[CHANNEL], SIDE_CHANNEL: claimed}
    assert [s.channel_id for s in r.discord.sends] == [SIDE_CHANNEL], "answered by guild, in the channel it was sent in"


def test_a_missed_message_in_a_home_channel_is_answered_on_taking_over() -> None:
    r = rig()
    missed = at(100)
    r.discord.backlog[CHANNEL] = [missed]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert r.discord.sends == [Sent(CHANNEL, "hi back", missed.id)]


def test_catch_up_keeps_only_messages_within_the_window_even_if_the_server_returns_older_ones() -> None:
    r = rig()
    r.discord.unfiltered = True
    r.discord.backlog[CHANNEL] = [at(700, content="stale"), at(100, content="fresh")]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert [i.text for i in r.replies.inbounds] == ["fresh"]


def test_catch_up_still_applies_the_routing_rules() -> None:
    r = rig()
    r.discord.backlog[CHANNEL] = [at(100, mentions_me=False), at(90, author_is_bot=True), at(80, author_id=GUEST_ID)]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.asked)
            await quiet()

    run(scenario())
    assert [i.text for i in r.replies.inbounds] == ["hello"], "only the guest's mention, answered as unknown"
    assert [i.speaker_id for i in r.replies.inbounds] == [None]


def test_a_message_found_by_catch_up_and_arriving_live_is_answered_once() -> None:
    r = rig()
    both = at(100)
    r.discord.backlog[CHANNEL] = [both]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)
            r.discord.incoming.put_nowait(both)
            await quiet()

    run(scenario())
    assert len(r.discord.sends) == 1 and len(r.replies.inbounds) == 1


def test_a_channel_whose_history_fails_does_not_stop_the_others_or_the_live_stream() -> None:
    r = rig([DiscordServer(FAMILY, GUILD, CHANNEL), DiscordServer(SECOND, OTHER_GUILD, OTHER_CHANNEL)])
    r.discord.history_errors[CHANNEL] = failed(500)
    r.discord.backlog[OTHER_CHANNEL] = [at(100, channel_id=OTHER_CHANNEL, guild_id=OTHER_GUILD)]
    live = message(id=snowflake(NOW) + 1)

    async def scenario() -> None:
        async with running(r) as task:
            await until(lambda: r.discord.sends)
            r.discord.incoming.put_nowait(live)
            await until(lambda: len(r.discord.sends) == 2)
            assert not task.done()

    run(scenario())
    assert [s.channel_id for s in r.discord.sends] == [OTHER_CHANNEL, CHANNEL]


def test_catch_up_survives_a_claim_store_that_can_neither_prune_nor_report_its_last_ids() -> None:
    r = rig()
    r.seen.unavailable = True
    r.discord.backlog[CHANNEL] = [at(100)]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.asked)

    run(scenario())
    assert asked(r) == {CHANNEL: snowflake(ago(600))}, "catch-up went on from the window start"


def test_a_message_made_exactly_at_the_window_start_is_caught_up() -> None:
    r = rig()
    r.discord.unfiltered = True
    r.discord.backlog[CHANNEL] = [at(600, content="edge")]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)

    run(scenario())
    assert [i.text for i in r.replies.inbounds] == ["edge"]


def test_old_claims_are_pruned_by_the_retention_in_days_when_the_lease_is_taken() -> None:
    r = rig(seen_retention_days=7)

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.seen.pruned)

    run(scenario())
    assert r.seen.pruned == [NOW - timedelta(days=7)]


def test_the_session_is_opened_once_and_closed_when_the_message_stream_ends_and_run_returns() -> None:
    r = rig()

    async def scenario() -> None:
        task = asyncio.create_task(r.bot.run())
        await until(lambda: r.connect.entered == 1)
        assert r.connect.exited == 0
        r.discord.incoming.put_nowait(None)
        await asyncio.wait_for(task, 3.0)
        assert task.exception() is None

    run(scenario())
    assert (r.connect.entered, r.connect.exited) == (1, 1)


def test_cancelling_cancels_the_replies_in_flight_and_closes_the_session() -> None:
    r = rig()
    r.replies.blocking = {"hello"}

    async def scenario() -> None:
        task = asyncio.create_task(r.bot.run())
        r.discord.incoming.put_nowait(message())
        await until(lambda: r.replies.inbounds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert r.connect.exited == 1
        r.replies.gate.set()
        await quiet()

    run(scenario())
    assert r.replies.cancelled == 1
    assert r.discord.sends == [], "a cancelled reply is never sent late"


def test_devices_being_unavailable_propagates_and_leaves_no_session_open() -> None:
    r = rig()
    r.devices.error = DevicesUnavailable("down")

    async def scenario() -> None:
        with pytest.raises(DevicesUnavailable):
            await asyncio.wait_for(r.bot.run(), 3.0)

    run(scenario())
    assert r.connect.entered == r.connect.exited


# --- logs: ids and counts, never content -----------------------------------------------------------------------------


def capture(r: Rig, feed: list[Message], sends: int, capsys: pytest.CaptureFixture[str]) -> str:
    """Everything logged while the bot is fed `feed` and has sent at least `sends` messages."""
    logs.setup()
    capsys.readouterr()

    async def scenario() -> None:
        async with running(r):
            for item in feed:
                r.discord.incoming.put_nowait(item)
            await until(lambda: len(r.discord.sends) >= sends)
            await quiet()

    run(scenario())
    return capsys.readouterr().out


def test_an_unwritable_claim_store_logs_seen_unavailable_not_a_generic_error(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    r.seen.unavailable = True
    out = capture(r, [message()], 0, capsys)
    reasons = [e["reason"] for e in events(out, "discord.failed")]
    assert "seen_unavailable" in reasons and "error" not in reasons


def test_a_bot_message_needs_no_lookup_even_when_people_is_down(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    r.people.error = PeopleUnavailable("down")
    out = capture(r, [message(author_is_bot=True)], 0, capsys)
    assert events(out, "discord.failed") == [] and r.people.asked == []
    assert [e["reason"] for e in events(out, "discord.ignored")] == ["bot"]


def test_connecting_and_answering_log_ids_counts_and_a_duration(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig([DiscordServer(FAMILY, GUILD, CHANNEL), DiscordServer(SECOND, OTHER_GUILD, OTHER_CHANNEL)])
    r.replies.body = "a" * 1500 + "\n\n" + "b" * 1500
    sent = message()
    out = capture(r, [sent], 2, capsys)
    [connected] = events(out, "discord.connected")        # contract: is `servers` the device count?
    assert connected["servers"] == "2"
    [replied] = events(out, "discord.replied")
    assert (replied["message"], replied["conversation"], replied["chunks"]) == (str(sent.id), "77", "2")
    assert replied["duration_ms"].replace(".", "").isdigit()


def test_catch_up_logs_how_many_messages_it_found(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    r.discord.backlog[CHANNEL] = [at(100), at(90)]
    out = capture(r, [], 2, capsys)
    [caught] = events(out, "discord.caught_up")
    assert caught["messages"] == "2"     # contract: counts the messages kept inside the window
    assert caught["channels"].isdigit()


@pytest.mark.parametrize(("sent", "reason"), [
    (message(author_is_bot=True), "bot"),
    (message(mentions_me=False), "not_addressed"),
    (message(guild_id=STRANGER_GUILD), "unknown_server"),
    (message(content="<@4242>"), "empty"),
])
def test_an_ignored_message_logs_its_id_and_why(sent: Message, reason: str, capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    out = capture(r, [sent], 0, capsys)
    [line] = events(out, "discord.ignored")
    assert (line["message"], line["reason"]) == (str(sent.id), reason)


def test_an_unmapped_dm_logs_the_user_id_so_the_admin_can_map_it(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    sent = message(author_id=GUEST_ID, content=SECRET, **DM)
    out = capture(r, [sent], 0, capsys)
    [line] = events(out, "discord.unmapped")
    assert (line["user"], line["message"]) == (str(GUEST_ID), str(sent.id))
    assert r.replies.inbounds == [] and r.discord.sends == []


def test_a_claim_lost_logs_claimed_elsewhere(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    sent = message()
    r.seen.preclaim(sent.id, CHANNEL, NOW)
    out = capture(r, [sent], 0, capsys)
    assert [e["message"] for e in events(out, "discord.claimed_elsewhere")] == [str(sent.id)]


def test_people_failing_and_a_failed_send_log_their_message_and_status(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    r.people.error = PeopleUnavailable("down")
    dropped = message()
    out = capture(r, [dropped], 0, capsys)
    [line] = events(out, "discord.failed")
    assert line["message"] == str(dropped.id) and line["reason"] != ""

    r = rig()
    r.discord.send_errors = {0: failed(403)}
    sent = message()
    out = capture(r, [sent], 1, capsys)
    [line] = events(out, "discord.send_failed")
    assert (line["message"], line["status"]) == (str(sent.id), "403")


def test_no_log_line_carries_message_content_or_her_reply(capsys: pytest.CaptureFixture[str]) -> None:
    reply = "reply-" + SECRET
    r = rig()
    r.replies.body = reply
    r.discord.send_errors = {2: failed(500)}    # the third send: the live message below that cannot be sent
    feed: list[Message] = [message(id=snowflake(NOW) + 1, content=f"<@4242> {SECRET}"),                  # answered
            message(id=snowflake(NOW) + 2, content=SECRET, mentions_me=False),            # not addressed
            message(id=snowflake(NOW) + 3, content=SECRET, author_id=GUEST_ID, **DM),     # unmapped DM
            message(id=snowflake(NOW) + 4, content=SECRET, author_is_bot=True),           # a bot
            message(id=snowflake(NOW) + 5, content=SECRET),                               # its send fails
            message(id=snowflake(NOW) + 6, content=SECRET, guild_id=STRANGER_GUILD)]    # unknown server
    r.seen.preclaim(snowflake(NOW) + 7, CHANNEL, ago(5000))      # claimed long ago: outside the catch-up window
    feed.append(message(id=snowflake(NOW) + 7, content=SECRET))                           # claimed elsewhere
    r.discord.backlog[CHANNEL] = [at(50, content=SECRET)]
    out = capture(r, feed, 3, capsys)
    assert len(events(out, "discord.replied")) >= 2, "control: the replies ran, so the lines were there to leak into"
    assert len(events(out, "discord.send_failed")) == 1 and events(out, "discord.ignored")
    assert SECRET not in out


def test_a_refusal_logs_no_content_either(capsys: pytest.CaptureFixture[str]) -> None:
    r = rig()
    r.replies.error = RespondRefused(SECRET)
    out = capture(r, [message(content=SECRET)], 1, capsys)
    assert SECRET not in out and r.discord.texts() == ["I would rather not."]
