"""A tool result too long for the place it is read, cut so the reader can see that it was: the marker leads, where a
model reads first and a cut mid-JSON cannot carry a flag, and says how much follows of how much there was."""

import json
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Cut:
    """`text` is the marker and then the first `shown` characters of a result `total` characters long, at most the
    limit it was cut to."""

    text: str
    shown: int
    total: int


def _marker(shown: int, total: int) -> str:
    return (f"[cut: only the first {shown} of {total} characters of this result follow; the rest was dropped, so what "
            "is not here is unseen, not absent. Ask for less, or for the rest if the tool takes an offset.]\n")


def visible(content: str, max_chars: int) -> Cut | None:
    """None when `content` fits `max_chars`; else the marker and as much of its head as the limit leaves room for."""
    if len(content) <= max_chars:
        return None
    head = content[:max(0, max_chars - len(_marker(max_chars, len(content))))]
    return Cut((_marker(len(head), len(content)) + head)[:max_chars], len(head), len(content))


def fit(whole: int, build: Callable[[int], dict[str, object]], budget: int) -> int:
    """The largest `n` in `0..whole` for which `build(n)`, serialized as `json.dumps(.., ensure_ascii=False)` as a tool
    result is, is at most `budget` characters; 0 when not even `build(0)` fits. `build` must not shrink as `n` grows."""
    low, high = 0, whole
    while low < high:
        middle = (low + high + 1) // 2
        if len(json.dumps(build(middle), ensure_ascii=False)) <= budget:
            low = middle
        else:
            high = middle - 1
    return low
