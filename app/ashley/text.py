"""Text that Postgres can hold. A NUL (U+0000) is valid in a Python or JSON string and in no text column, jsonb
included, so it is refused where a person or device sends it (`NoNul`) and removed where her own model writes it
(`Cleaned`) and where outside text no person can retype enters (`without_nul`)."""

import logging
from typing import Annotated, Literal

from pydantic import AfterValidator

from . import logs

log = logging.getLogger("ashley.text")


def _refuse(text: str) -> str:
    if "\x00" in text:
        raise ValueError("text holds a NUL character")
    return text


def _remove(text: str) -> str:
    return text.replace("\x00", "")


NoNul = Annotated[str, AfterValidator(_refuse)]
"""A `str` field of a wire model that refuses a NUL, as a 422 like any other bad input."""

Cleaned = Annotated[str, AfterValidator(_remove)]
"""A `str` field of what her model writes, with any NUL removed as it is read, so the rest of her words still reach the
person."""


def has_nul(text: str) -> bool:
    return "\x00" in text


def without_nul(text: str, channel: Literal["voice", "mail"]) -> str:
    """`text` with every NUL removed, for outside text no person can retype (a transcript, a mail body); one
    `text.nul_stripped` line says how many went, never what was around them."""
    count = text.count("\x00")
    if count:
        logs.info(log, "text.nul_stripped", channel=channel, count=count)
    return text.replace("\x00", "")
