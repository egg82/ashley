"""`client.forwarded_text` reads the text of the messages a Discord message forwards (its snapshots): the ones with text,
joined by a blank line, and "" when there are none, so a forward of only a picture is no block."""

from hikari import MessageType, undefined
from hikari.messages import MessageSnapshot

from ashley.channels.discord.client import forwarded_text


def snapshot(content: str | None) -> MessageSnapshot:
    return MessageSnapshot(type=MessageType.DEFAULT, content=content, embeds=(), attachments=(), timestamp=undefined.UNDEFINED,
                           edited_timestamp=None, flags=undefined.UNDEFINED, stickers=(), user_mentions={},
                           role_mention_ids=(), components=())


def test_forwarded_text_messages_with_text_are_joined_by_a_blank_line() -> None:
    assert forwarded_text([snapshot("first"), snapshot("second\nline")]) == "first\n\nsecond\nline"


def test_a_forward_with_no_text_is_empty_and_so_is_a_message_forwarding_nothing() -> None:
    assert forwarded_text([snapshot(None), snapshot("")]) == "" and forwarded_text([]) == "" and forwarded_text(None) == ""


def test_a_snapshot_without_text_is_skipped_among_ones_with_it() -> None:
    assert forwarded_text([snapshot(None), snapshot("kept"), snapshot("")]) == "kept"
