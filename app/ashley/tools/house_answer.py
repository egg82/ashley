"""What one of her house tools returns before `HouseTools` logs and wraps it: compact JSON no longer than the cap, the
first of several forms (most detail first) that fits, and the fields its `tools.call` line carries."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

Body = dict[str, Any]


@dataclass(frozen=True)
class Answer:
    text: str
    is_error: bool = False
    fields: Mapping[str, str | int | bool] = field(default_factory=dict[str, str | int | bool])
    outside: bool | None = None


def dumps(body: object) -> str:
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False, default=str)


def fit(forms: list[Body], max_chars: int) -> tuple[str, int]:
    """The text of the first form that fits `max_chars` and its index; the last form when none does. A form that cannot
    show everything says so itself (`complete`), so nothing is ever cut mid-list."""
    for index, form in enumerate(forms[:-1]):
        text = dumps(form)
        if len(text) <= max_chars:
            return text, index
    return dumps(forms[-1]), len(forms) - 1


def error(message: str, **fields: str | int | bool) -> Answer:
    return Answer(message, True, fields)
