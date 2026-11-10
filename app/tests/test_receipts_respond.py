"""A whole tainted turn through `respond`: her reply is exactly what the model wrote on every wire, the change that ran
beside it is in the receipts of the turn she stored, and a spoken turn says none of it."""

import asyncio
from collections.abc import Coroutine, Generator, Sequence
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.respond import respond
from ashley.inference.model import ToolSpec
from ashley.inference.reply import Reply
from ashley.senses.outside_record import OutsideRecord
from ashley.channels.model import Outbound
from ashley.tools.action_judge import ActionJudge, Verdict, View
from outside_record_support import MemoryRecord
from respond_support import ALANA, Fakes, calls, inbound, wired as wired

WORDS = "Okay."


class Runs(ActionJudge):
    async def decide(self, words: Sequence[str], view: View) -> Verdict:
        return Verdict("run", "asked_directly", "You asked for it.")


def outcome(turn: Coroutine[None, None, Outbound]) -> Outbound:
    return asyncio.run(turn)
LAMP = ToolSpec("lamp", "the lamp", {"type": "object"}, label="Turned on the lamp")
LOOK = ToolSpec("look", "read a page", {"type": "object"}, reads=True, outside=True)


@pytest.fixture(autouse=True)
def judged(wired: Fakes) -> Generator[None]:
    wired.tools.specs = (LOOK, LAMP)
    services.register(ActionJudge, Runs())
    services.register(OutsideRecord, MemoryRecord())
    yield
    services.unregister(ActionJudge)
    services.unregister(OutsideRecord)


def tainted(medium: str = "text") -> Inbound:
    made = inbound("turn on the lamp", thread=f"person:{ALANA.id}:web", medium=medium, shared=False, speaker_id=ALANA.id,
                   kind="chat")
    return replace(made, audience="owner")


def test_a_judged_change_that_ran_is_in_the_receipts_of_her_turn_though_her_reply_says_nothing_of_it(wired: Fakes) -> None:
    wired.inference.script = [calls("look", "lamp"), Reply(spoken=WORDS, text=WORDS)]
    out = outcome(respond(tainted()))
    assert out.body == WORDS
    [hers] = [t for t in wired.conversations.added if t.author == "ashley"]
    assert hers.text == WORDS and hers.receipts is not None
    assert [r.headline for r in hers.receipts.done] == ["Turned on the lamp"] and hers.receipts.held == ()
    assert out.receipts == hers.receipts


def test_a_spoken_turn_says_only_her_words_and_keeps_the_receipts_on_her_stored_turn(wired: Fakes) -> None:
    wired.inference.script = [calls("look", "lamp"), Reply(spoken=WORDS, text="Written.")]
    out = outcome(respond(tainted("spoken")))
    assert out.body == WORDS
    [hers] = [t for t in wired.conversations.added if t.author == "ashley"]
    assert hers.text == WORDS and hers.receipts is not None and "lamp" not in hers.text.lower()


def test_a_tainted_turn_that_only_read_stores_no_receipts(wired: Fakes) -> None:
    wired.inference.script = [calls("look"), Reply(spoken=WORDS, text=WORDS)]
    out = outcome(respond(tainted()))
    [hers] = [t for t in wired.conversations.added if t.author == "ashley"]
    assert out.receipts is None and hers.receipts is None
