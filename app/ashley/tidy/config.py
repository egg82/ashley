"""The tidy pass's tunables, data in `tidy.json` beside this module: which piece kinds it reads, how much of one piece and
of the whole bench goes to the model, how many findings it keeps and a bench read shows, the bounds on a finding's quote
and reason, how long one pass holds a bench before another may take it (`lock_s`), and how long a finding is kept
(`keep_s`)."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

FILE = Path(__file__).with_name("tidy.json")


class TidyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kinds: tuple[str, ...] = Field(min_length=1)
    max_piece_chars: PositiveInt
    max_total_chars: PositiveInt
    max_findings: PositiveInt
    shown: PositiveInt
    min_quote_chars: PositiveInt
    max_quote_chars: PositiveInt
    max_why_chars: PositiveInt
    lock_s: PositiveInt
    keep_s: PositiveInt

    @model_validator(mode="after")
    def _quote_bounds(self) -> Self:
        if self.min_quote_chars > self.max_quote_chars:
            raise ValueError("min_quote_chars is more than max_quote_chars")
        return self


def load() -> TidyConfig:
    """The tunables shipped in `tidy.json`. Raises pydantic's ValidationError (a ValueError) when a key is missing or
    unknown, `kinds` is empty, a number is not positive or the quote bounds are reversed."""
    return TidyConfig.model_validate_json(FILE.read_text())
