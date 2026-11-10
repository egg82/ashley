"""`channels.respond` over fakes: a reply with nothing to deliver is asked again once, then the turn stores and
delivers the fixed line; an empty turn is never stored; `Unstored` keeps what refused the turn."""

import asyncio

import pytest
from ashley import logs
from ashley.channels.inflight import Unstored
from ashley.channels.model import Medium
from ashley.channels.respond import respond
from ashley.conversations.conversations import ConversationClosed
from ashley.inference.reply import Reply
from contract.conversations_support import events
from respond_support import Fakes, inbound, wired as wired
from answer_dropped_blind_support import (BLANK, EMPTIES, EMPTY, GOOD, LINE, SAID_ONLY, SENTINEL, WRITTEN_ONLY, delivered)

MEDIA: list[Medium] = ["text", "spoken"]


def hers(fakes: Fakes) -> list[str]:
    conv = next(iter(fakes.conversations.convs.values()))
    return [t.text for t in conv.turns if t.author == "ashley"]


@pytest.mark.parametrize("medium", MEDIA)
@pytest.mark.parametrize("empty", EMPTIES)
def test_an_empty_first_reply_is_asked_again_and_only_the_second_is_stored_and_delivered(
        wired: Fakes, capsys: pytest.CaptureFixture[str], medium: Medium, empty: Reply) -> None:
    logs.setup()
    wired.inference.script = [empty, GOOD]
    out = asyncio.run(respond(inbound(medium=medium)))
    assert out.body == delivered(GOOD, medium)
    assert hers(wired) == [delivered(GOOD, medium)]
    assert len(wired.inference.prompts) == 2
    seen = capsys.readouterr().out
    assert len(events(seen, "respond.reply_empty")) == 1 and events(seen, "respond.failed") == []


@pytest.mark.parametrize("medium", MEDIA)
@pytest.mark.parametrize("empty", EMPTIES)
def test_two_empty_replies_store_and_deliver_the_fixed_line_once(wired: Fakes, medium: Medium, empty: Reply) -> None:
    wired.inference.script = [empty, empty]
    out = asyncio.run(respond(inbound(medium=medium)))
    assert out.body == LINE and out.medium == medium
    assert hers(wired) == [LINE]
    assert len(wired.inference.prompts) == 2


@pytest.mark.parametrize(("medium", "reply"), [("spoken", WRITTEN_ONLY), ("text", SAID_ONLY)])
def test_text_in_the_field_the_medium_does_not_deliver_does_not_save_the_turn(wired: Fakes, medium: Medium, reply: Reply) -> None:
    wired.inference.script = [reply, reply]
    out = asyncio.run(respond(inbound(medium=medium)))
    assert out.body == LINE and hers(wired) == [LINE]


@pytest.mark.parametrize(("medium", "reply"), [("text", WRITTEN_ONLY), ("spoken", SAID_ONLY)])
def test_the_mediums_own_field_alone_is_delivered_without_a_second_ask(wired: Fakes, medium: Medium, reply: Reply) -> None:
    wired.inference.script = [reply]
    out = asyncio.run(respond(inbound(medium=medium)))
    assert out.body == delivered(reply, medium) and len(wired.inference.prompts) == 1


def test_no_empty_turn_of_hers_is_ever_added_to_the_conversation(wired: Fakes) -> None:
    wired.inference.script = [BLANK, EMPTY]
    asyncio.run(respond(inbound()))
    assert [t.text for t in wired.conversations.added if t.author == "ashley"] == [LINE]


@pytest.mark.parametrize("medium", MEDIA)
def test_no_content_reaches_a_log_line(wired: Fakes, capsys: pytest.CaptureFixture[str], medium: Medium) -> None:
    """The person's words, the other medium's text and the offer all carry the sentinel; the log carries none of it."""
    logs.setup()
    leaky = Reply(spoken="" if medium == "spoken" else SENTINEL, text="" if medium == "text" else SENTINEL, offer=SENTINEL)
    wired.inference.script = [leaky, leaky]
    asyncio.run(respond(inbound(f"please {SENTINEL}", medium=medium)))
    seen = capsys.readouterr()
    assert len(events(seen.out, "respond.reply_empty")) >= 1
    assert SENTINEL not in seen.out + seen.err


def test_unstored_keeps_the_cause_class_and_the_check_phrase() -> None:
    refused = Unstored(ValueError("a turn has text"))
    assert (refused.cause, refused.check) == ("ValueError", "a turn has text")
    closed = Unstored(ConversationClosed(3))
    assert (closed.cause, closed.check) == ("ConversationClosed", "")
