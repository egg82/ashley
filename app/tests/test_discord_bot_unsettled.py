"""A claim whose session died before the turn loop took the message in hand: the bot settles each claim once `respond`
has returned or raised, and a session catching up hands in again each claim never settled, from its own message on,
without claiming it twice; the turn loop makes the second hand-in the same person turn (`Inbound.source`)."""

import asyncio
from collections.abc import Generator

import pytest
from ashley.channels.discord.message import Message
from ashley.channels.respond import RespondUnavailable
from contract.conversations_support import run
from discord_support import CHANNEL, Rig, Sent, ago, message, quiet, rig, running, snowflake, unwire, until


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    yield
    unwire()


def at(seconds_ago: float, **changes: object) -> Message:
    return message(**{"id": snowflake(ago(seconds_ago)), **changes})


def asked(r: Rig) -> dict[int, int]:
    return {channel: after for channel, after, _ in r.discord.asked}


def test_a_claim_is_settled_once_her_reply_is_made() -> None:
    r = rig()
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert r.seen.settled == {sent.id}


def test_a_claim_is_settled_when_the_turn_loop_could_not_answer() -> None:
    r = rig()
    r.replies.error = RespondUnavailable()
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert r.seen.settled == {sent.id}


def test_a_claim_whose_reply_was_cut_off_stays_unsettled() -> None:
    r = rig()
    sent = message(content="slow")
    r.replies.blocking = {"slow"}

    async def scenario() -> None:
        task = asyncio.create_task(r.bot.run())
        r.discord.incoming.put_nowait(sent)
        await until(lambda: r.replies.inbounds)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert sent.id in r.seen.claims and r.seen.settled == set()


def test_catch_up_hands_in_again_a_claim_never_settled_and_settles_it() -> None:
    r = rig()
    stranded = at(300, content="stranded")
    later = at(200, content="later")
    r.seen.preclaim(stranded.id, CHANNEL, ago(300), settled=False)
    r.seen.preclaim(later.id, CHANNEL, ago(200))
    r.discord.backlog[CHANNEL] = [stranded, later]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.sends)
            await quiet()

    run(scenario())
    assert asked(r)[CHANNEL] < stranded.id, "read from before the stranded message"
    assert [i.text for i in r.replies.inbounds] == ["stranded"], "the settled claim after it is not answered again"
    assert r.discord.sends == [Sent(CHANNEL, "hi back", stranded.id)]
    assert r.seen.settled == {stranded.id, later.id}


def test_a_claim_settled_meanwhile_is_not_handed_in_again() -> None:
    r = rig()
    done = at(300)
    r.seen.preclaim(done.id, CHANNEL, ago(300))
    r.discord.backlog[CHANNEL] = [done]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.asked)
            await quiet()

    run(scenario())
    assert r.replies.inbounds == [] and r.discord.sends == []


def test_an_unsettled_claim_older_than_the_window_is_left() -> None:
    r = rig()
    old = at(5000)
    r.seen.preclaim(old.id, CHANNEL, ago(5000), settled=False)
    r.discord.backlog[CHANNEL] = [old]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.discord.asked)
            await quiet()

    run(scenario())
    assert r.replies.inbounds == []


def test_the_message_handed_in_carries_its_source() -> None:
    r = rig()
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.discord.sends)

    run(scenario())
    assert [i.source for i in r.replies.inbounds] == [f"discord:{sent.id}"]


def test_a_reply_with_no_words_sends_nothing_and_settles() -> None:
    r = rig()
    r.replies.body = ""
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.seen.settled)
            await quiet()

    run(scenario())
    assert r.discord.sends == []


def test_a_claim_is_settled_when_the_turn_loop_fails_unexpectedly() -> None:
    r = rig()
    r.replies.error = RuntimeError("boom")
    sent = message()

    async def scenario() -> None:
        async with running(r):
            r.discord.incoming.put_nowait(sent)
            await until(lambda: r.seen.settled)
            await quiet()

    run(scenario())
    assert r.seen.settled == {sent.id} and r.discord.sends == []


def test_a_stranded_claim_she_would_not_answer_now_is_settled_and_not_answered() -> None:
    r = rig()
    stranded = at(300, author_is_bot=True)
    r.seen.preclaim(stranded.id, CHANNEL, ago(300), settled=False)
    r.discord.backlog[CHANNEL] = [stranded]

    async def scenario() -> None:
        async with running(r):
            await until(lambda: r.seen.settled)
            await quiet()

    run(scenario())
    assert r.replies.inbounds == [] and r.discord.sends == []
    assert r.seen.settled == {stranded.id}
