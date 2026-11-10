"""What the person is shown of a held call, written by code from the tool's name and its arguments and never by the
model: the detail of a receipt for a held call (`ashley.tools.outside.Outside.receipts`) and the record of what ran
(`done_summary`)."""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_WORD = re.compile(r"[a-z0-9_.]{1,64}")


def arguments_chars(arguments: Mapping[str, object]) -> int:
    """How many characters the arguments take as stored JSON."""
    return len(json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str))


def summary(label: str, arguments: Mapping[str, object]) -> str:
    """The change's plain label, then every argument in full, in the order given, each value as JSON. Never the tool's name."""
    shown = ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False, default=str)}" for k, v in arguments.items())
    return f"{label} ({shown})" if shown else label


def done_summary(label: str, arguments: Mapping[str, object], named: Sequence[str]) -> str:
    """The plain label for a change that ran, and the arguments in `named` that hold a word of the shape of an action or
    a folder (`light.turn_on`, `archive`). Nothing else of the arguments is shown, so no text the model was given or
    wrote reaches the record."""
    shown = ", ".join(f"{k}: {v}" for k in named if isinstance(v := arguments.get(k), str) and _WORD.fullmatch(v))
    return f"{label} ({shown})" if shown else label


def block(intro: str, summaries: list[str]) -> str:
    """The intro line, then each summary on a line of its own."""
    return "\n".join([intro, *(f"- {s}" for s in summaries)])


def plain(arguments: Mapping[str, object]) -> dict[str, Any]:
    """The arguments as stored JSON: what a round trip through the store gives back."""
    return dict(json.loads(json.dumps(arguments, default=str)))
