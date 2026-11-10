"""What is typed to her: a message on a web thread or a bench's talk, and the paste that may come with it."""

from pydantic import BaseModel, ConfigDict, Field

from ..text import NoNul


class ChatRequest(BaseModel):
    """What was typed to her on a web thread (a person's own, or the kiosk's): `text`, 1 to 4000 characters and
    not only whitespace."""

    model_config = ConfigDict(extra="forbid")

    text: NoNul = Field(min_length=1, max_length=4000, pattern=r"\S")


ATTACHMENT_MAX_CHARS = 20000
ATTACHMENT_TITLE_MAX_CHARS = 120


class ChatAttachment(BaseModel):
    """A block of text a person pasted with a message: `text`, 1 to 20000 characters and not only whitespace, and a
    `title` of up to 120 characters when it has one. It is her to read in full, beside the message and never in place
    of it."""

    model_config = ConfigDict(extra="forbid")

    title: NoNul | None = Field(default=None, min_length=1, max_length=ATTACHMENT_TITLE_MAX_CHARS)
    text: NoNul = Field(min_length=1, max_length=ATTACHMENT_MAX_CHARS, pattern=r"\S")


class ChatMessage(ChatRequest):
    """A message on the person's own web thread: `text` as `ChatRequest`, and the `attachment` they pasted with it,
    which is kept with their turn and shown folded under it. `said_aloud` says the words came from the page's record
    button (tap to talk), which offers her to answer aloud (`channels.aloud`)."""

    attachment: ChatAttachment | None = None
    said_aloud: bool = False


class KioskMessage(ChatRequest):
    """A message on the kiosk's thread: `text` as `ChatRequest`. `said_aloud` says the words came from the page's record
    button (tap to talk), which offers her to answer aloud (`channels.aloud`)."""

    said_aloud: bool = False


class BenchMessage(ChatRequest):
    """A message on a bench's talk: `text` as `ChatRequest`, and `piece_id` when the person just put a paste on the
    bench as that piece (a document of theirs), which she is told of with the message."""

    piece_id: int | None = Field(default=None, ge=1)
