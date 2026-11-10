"""`discord.later`: a reply said to `discord:<channel_id>` is posted in that channel, split as any reply is into
2000-character messages (at most `max_messages`), none as a reply to a message; a failed send ends that reply's
remaining messages; `discord.later` logs the counts. `drain` takes `discord:` every poll, posting each reply, and logs
`discord.outbox_unavailable` once per run of failures."""

import pytest
from ashley.channels.discord.chunks import chunks
from ashley.channels.outbox import Later
from ashley.channels.discord.later import drain, post
from contract.conversations_support import run
from discord_support import CHANNEL, SECRET, FakeDiscord, config, failed
from later_support import FakeOutbox, Logged, Polls, drained, outbox as outbox, unavailable, waiting

LONG = " ".join(f"word{n}" for n in range(1500))   # ~10k characters of spaced words


def reply(body: str = "It is dry.", channel: int = CHANNEL, age_ms: int = 2500) -> Later:
    return waiting(f"discord:{channel}", body, medium="text", age_ms=age_ms)


def posted(discord: FakeDiscord, later: Later, max_messages: int = 4) -> None:
    async def scenario() -> None:
        await post(discord, later, config(max_messages=max_messages))

    run(scenario())


def test_a_short_reply_is_one_message_in_its_channel_not_a_reply() -> None:
    discord = FakeDiscord()
    posted(discord, reply("It is dry.", channel=1234))
    assert [(s.channel_id, s.text, s.reply_to) for s in discord.sends] == [(1234, "It is dry.", None)]


def test_a_long_reply_is_split_as_any_reply_is_with_none_a_reply() -> None:
    discord = FakeDiscord()
    posted(discord, reply(LONG), max_messages=10)
    assert discord.texts() == chunks(LONG, 2000, 10)
    assert len(discord.sends) > 1 and all(len(t) <= 2000 for t in discord.texts())
    assert all(s.reply_to is None and s.channel_id == CHANNEL for s in discord.sends)


def test_no_more_than_max_messages_are_sent() -> None:
    discord = FakeDiscord()
    posted(discord, reply(LONG), max_messages=2)
    assert discord.texts() == chunks(LONG, 2000, 2)
    assert len(discord.sends) == 2


def test_a_failed_send_ends_the_replys_remaining_messages() -> None:
    discord = FakeDiscord()
    discord.send_errors = {1: failed(500)}
    posted(discord, reply(LONG), max_messages=10)
    assert len(discord.sends) == 2, "the failed second message is the last attempt"


def test_a_failed_send_does_not_stop_the_next_reply() -> None:
    discord = FakeDiscord()
    discord.send_errors = {0: failed(403)}
    posted(discord, reply("first"))
    posted(discord, reply("second"))
    assert discord.texts() == ["first", "second"]


def test_the_log_carries_the_channel_conversation_chunks_and_age_but_no_words(
        capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    discord = FakeDiscord()
    posted(discord, waiting(f"discord:{CHANNEL}", SECRET + " " + LONG, conversation_id=88, medium="text",
                            age_ms=2500), max_messages=2)
    (line,) = log.events("discord.later")
    assert {str(CHANNEL), "88", "2", "2500"} <= set(line.values())
    assert SECRET not in log.read()


def test_drain_takes_the_discord_threads_each_poll_and_posts_each_reply(outbox: FakeOutbox) -> None:
    discord = FakeDiscord()
    outbox.waiting = [waiting("discord:10", "one", id_=1, medium="text"),
                      waiting("device:3", "elsewhere", id_=2),
                      waiting("discord:11", "two", id_=3, medium="text")]
    polls = Polls(stop_at=3)

    async def scenario() -> None:
        await drained(drain(discord, config(max_messages=4), 0.25, polls))

    run(scenario())
    assert [(s.channel_id, s.text, s.reply_to) for s in discord.sends] == [(10, "one", None), (11, "two", None)]
    assert set(outbox.prefixes) == {"discord:"} and len(outbox.prefixes) >= 2
    assert polls.waits == [0.25] * 3
    assert [w.thread for w in outbox.waiting] == ["device:3"]


def test_a_run_of_outbox_failures_is_logged_once_and_the_drain_keeps_going(
        outbox: FakeOutbox, capsys: pytest.CaptureFixture[str]) -> None:
    discord = FakeDiscord()
    outbox.take_errors = [unavailable(), unavailable(), None, unavailable(), None, None]
    outbox.waiting = [waiting(f"discord:{CHANNEL}", "after", medium="text")]
    log = Logged(capsys)
    polls = Polls(stop_at=6)

    async def scenario() -> None:
        await drained(drain(discord, config(max_messages=4), 0.01, polls))

    run(scenario())
    assert len(log.events("discord.outbox_unavailable")) == 2, "one line per run of failures, two runs"
    assert discord.texts() == ["after"]
