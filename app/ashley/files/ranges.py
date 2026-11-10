"""A `Range` request header over a file of known size, for a player that seeks: one byte range, `a-b`, `a-` or `-n`.
Pure."""

import re
from typing import Literal

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
Unsatisfiable = Literal["unsatisfiable"]


def parse(header: str | None, size: int) -> tuple[int, int] | Unsatisfiable | None:
    """The inclusive byte range `(first, last)` `header` asks of a `size`-byte file, clipped to the file; None when
    there is no header or it is not one single range (the whole file is then served, as the standard allows);
    `"unsatisfiable"` when the range starts past the end or asks for no bytes."""
    found = _RANGE.fullmatch((header or "").strip())
    if found is None or not (found[1] or found[2]):
        return None
    first, last = found[1], found[2]
    if not first:
        wanted = int(last)
        return "unsatisfiable" if wanted == 0 else (max(0, size - wanted), size - 1)
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    return "unsatisfiable" if start >= size or end < start else (start, end)
