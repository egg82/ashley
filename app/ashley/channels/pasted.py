"""Whether a block a person pasted or forwarded with a message makes the turn `pasted` (`channels.taint`): the text of
such a block can address the action judge, so a turn carrying more than `taint_chars` characters of it starts tainted,
and the block is never among the judge's words (`channels.judge_words`). The threshold is data, `pasted.json` beside
this module."""

import json
from pathlib import Path

from ..conversations.model import Attachment
from .model import Taint

FILE = Path(__file__).with_name("pasted.json")


def threshold() -> int:
    """`taint_chars` of `pasted.json`. Raises ValueError when the file has anything else or it is not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != {"taint_chars"} or not isinstance(raw["taint_chars"], int) or raw["taint_chars"] < 1:
        raise ValueError("pasted.json has exactly taint_chars, a positive integer")
    return raw["taint_chars"]


def taint_of(attachment: Attachment | None) -> Taint | None:
    """`pasted` when `attachment` is longer than `taint_chars` characters, else None (no attachment included)."""
    return "pasted" if attachment is not None and len(attachment.text) > threshold() else None
