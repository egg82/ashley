"""Her reply split for Discord's message limit."""

_BREAKS = ("\n\n", "\n", " ")
_MORE = "…"


def chunks(text: str, limit: int = 2000, most: int = 4) -> list[str]:
    """`text` split into at most `most` pieces of at most `limit` characters each, none empty or all whitespace,
    cutting at the last paragraph break (`\\n\\n`) within the limit, else the last line break, else the last space,
    else at the limit. Pieces are stripped of surrounding whitespace. Joined back with the breaks they were cut at,
    they reproduce the stripped text when it fits; when it does not, the last piece ends with `…` and is still within
    `limit`. Empty or whitespace-only text gives []. ValueError when `limit` < 2 or `most` < 1."""
    if limit < 2 or most < 1:
        raise ValueError("chunks needs limit >= 2 and most >= 1")
    rest = text.strip()
    pieces: list[str] = []
    while rest:
        if len(rest) <= limit:
            pieces.append(rest)
            break
        if len(pieces) == most - 1:
            pieces.append(rest[:_cut(rest, limit - 1)].rstrip() + _MORE)
            break
        at = _cut(rest, limit)
        pieces.append(rest[:at].rstrip())
        rest = rest[at:].lstrip()
    return pieces


def _cut(text: str, limit: int) -> int:
    """Where to end a piece of at most `limit` characters of `text` (stripped, longer than `limit`): before the last
    break of the first kind in `_BREAKS` that starts after the first character and fits, else at `limit`."""
    for brk in _BREAKS:
        at = text.rfind(brk, 1, limit + len(brk))
        if at > 0:
            return at
    return limit
