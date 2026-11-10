"""Where a carried turn was said, as the prompt marks it beside when (`label`), from the thread its conversation
carries."""

import json

from ..conversations.model import Place

_TITLE_CHARS = 60

_KINDS = (("person:", ":web", "web chat"), ("device:", "", "a device"), ("push:", "", "the phone"),
          ("discord:", "", "Discord"))


def label(place: Place) -> str:
    """`bench 4 "Shelf bracket"` for a bench's thread, else a plain name for the kind of thread. A title is quoted as
    JSON, so a quote, a newline or a bracket in it cannot end the mark, and cut to its first `_TITLE_CHARS` characters."""
    if place.thread.startswith("bench:"):
        number = f"bench {place.thread.removeprefix('bench:')}"
        return number if place.bench_title is None else f"{number} {_quoted(place.bench_title)}"
    for start, end, name in _KINDS:
        if place.thread.startswith(start) and place.thread.endswith(end):
            return name
    return "elsewhere"


def _quoted(title: str) -> str:
    one_line = " ".join(title.split())
    cut = one_line if len(one_line) <= _TITLE_CHARS else one_line[:_TITLE_CHARS - 1] + "…"
    return json.dumps(cut, ensure_ascii=False)
