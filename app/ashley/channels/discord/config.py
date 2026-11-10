"""The Discord adapter's tunables, as data in `discord.json` beside this module, validated when loaded.

A reply is sent as at most `max_messages` Discord messages. On taking the lease she catches up on messages younger than
`catch_up_s`; claims are kept `seen_retention_days`, which must outlast the catch-up. While she thinks, typing is shown
again every `typing_refresh_s` (Discord shows it for about 10 s). `unavailable_text` is posted when she cannot answer
for want of a system, `refused_text` when the model declined. The small message under a reply that did or held changes
(`receipts.receipt_lines`) ends with `held_footer` when any waits."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

FILE = Path(__file__).with_name("discord.json")
_LIMIT = 2000   # Discord's longest message


@dataclass(frozen=True)
class Config:
    max_messages: int
    catch_up_s: float
    seen_retention_days: float
    typing_refresh_s: float
    unavailable_text: str
    refused_text: str
    held_footer: str

    def __post_init__(self) -> None:
        if self.max_messages < 1:
            raise ValueError("max_messages must be at least 1")
        if min(self.catch_up_s, self.seen_retention_days, self.typing_refresh_s) <= 0:
            raise ValueError("discord timings must be positive")
        if self.seen_retention_days * 86400 <= self.catch_up_s:
            raise ValueError("seen_retention_days must outlast catch_up_s")
        for text in (self.unavailable_text, self.refused_text):
            if not text.strip() or len(text) > _LIMIT:
                raise ValueError("unavailable_text and refused_text must be non-blank and fit one Discord message")
        if not self.held_footer.strip():
            raise ValueError("held_footer must be non-blank")


def parse(raw: dict[str, Any]) -> Config:
    """A Config from the decoded JSON. Raises ValueError naming a key that is missing, unknown or of the wrong type."""
    expected = {f.name: f.type for f in fields(Config)}
    if set(raw) != set(expected):
        raise ValueError(f"discord.json keys: missing {sorted(set(expected) - set(raw))}, "
                         f"unknown {sorted(set(raw) - set(expected))}")
    for key, value in raw.items():
        text = expected[key] is str
        number = isinstance(value, int | float) and not isinstance(value, bool)
        if not (isinstance(value, str) if text else number):
            raise ValueError(f"discord.json.{key} must be {'text' if text else 'a number'}")
    if not isinstance(raw["max_messages"], int):
        raise ValueError("discord.json.max_messages must be a whole number")
    return Config(**raw)


def load(path: Path = FILE) -> Config:
    return parse(json.loads(path.read_text(encoding="utf-8")))
