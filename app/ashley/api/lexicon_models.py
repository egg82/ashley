"""The wire models of the household's pronunciation words (`ashley.api.lexicon`)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..channels.lexicon import Refusal
from ..text import NoNul
from .models import Person


class LexiconWord(BaseModel):
    """`real` is the word as written, `spoken` the spelling the voice says right. `edited_by` is the person who last set
    it, null once they are gone."""

    real: str
    spoken: str
    updated_at: datetime
    edited_by: Person | None


class LexiconWords(BaseModel):
    """The signed-in person's household's words by `real`, and the most it holds."""

    words: list[LexiconWord]
    limit: int


class LexiconWordRequest(BaseModel):
    """The spelling to say for the word in the path."""

    spoken: NoNul = Field(max_length=500)


class LexiconRefused(BaseModel):
    """Why `refused_for` a word was not stored: `not_a_word` (the path is not one word-like token), `blank_spelling`,
    `too_long` (the word or its spelling is over 64 characters) or `full` (the household holds the most it may)."""

    refused_for: Refusal | Literal["full"]
    detail: str
