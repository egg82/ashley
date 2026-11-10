"""On a channel the person reads on a page (`Inbound.paged`), a turn that fails or is kept for retry stores no turn of
hers with words code wrote: the page is told its state through Live and words it itself. A spoken channel still says
the fixed line."""

import asyncio
from dataclasses import replace

import pytest
from ashley.channels import unsaid
from ashley.channels.respond import RespondUnavailable, respond
from ashley.inference.inference import InferenceRejected
from ashley.inference.reply import Reply
from respond_support import ALANA, Fakes, inbound, wired as wired

PAGED = replace(inbound(thread="person:11:web", speaker_id=ALANA.id, kind="chat", shared=False), audience="owner",
                later=True, later_by="turn")
SPOKEN = inbound(thread="device:7", speaker_id=ALANA.id, medium="spoken")


def hers(wired: Fakes) -> list[str]:
    return [t.text for t in wired.conversations.added if t.author == "ashley"]


def test_a_rejected_request_on_a_page_stores_no_turn_of_hers(wired: Fakes) -> None:
    wired.inference.script = [InferenceRejected("every route rejected the request")]
    with pytest.raises(RespondUnavailable):
        asyncio.run(respond(PAGED))
    assert hers(wired) == []


def test_a_rejected_request_on_a_spoken_channel_still_says_the_line(wired: Fakes) -> None:
    wired.inference.script = [InferenceRejected("every route rejected the request")]
    out = asyncio.run(respond(SPOKEN))
    assert out.body == unsaid.REJECTED and hers(wired) == [unsaid.REJECTED]


def test_an_empty_answer_on_a_page_stores_no_line_and_on_a_spoken_channel_says_it(wired: Fakes) -> None:
    blank = Reply(spoken="", text="")
    wired.inference.script = [blank, blank, blank]
    with pytest.raises(RespondUnavailable):
        asyncio.run(respond(PAGED))
    assert hers(wired) == []
    wired.inference.script = [blank, blank, blank]
    assert asyncio.run(respond(SPOKEN)).body == unsaid.LINE
