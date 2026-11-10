"""`render`: the `spoken` field for a spoken medium, the `text` field for text, each whole. With no household, or one
with no words, a sentence comes back unchanged."""

import asyncio

from ashley.channels.render import render
from ashley.inference.reply import Reply
from hypothesis import given, settings
from hypothesis import strategies as st

REPLY = Reply(spoken="The kitchen light is on.", text="**Kitchen** light: [on](https://example.invalid).")


def test_spoken_is_the_spoken_field() -> None:
    assert asyncio.run(render(REPLY, "spoken", None)) == REPLY.spoken


def test_text_is_the_text_field() -> None:
    assert asyncio.run(render(REPLY, "text", None)) == REPLY.text


@settings(max_examples=30, deadline=None)
@given(st.text(st.characters(exclude_characters="\x00"), min_size=1, max_size=200))
def test_text_is_never_altered(text: str) -> None:
    assert asyncio.run(render(Reply(spoken="said", text=text), "text", 1)) == text
