"""A bench opened with an ask is titled from the ask until she names it (`Rename`)."""

ELLIPSIS = "…"


def provisional_title(ask: str, max_chars: int) -> str:
    """`ask` on one line, whitespace collapsed; when longer than `max_chars`, cut at the last word that fits with an
    ellipsis (at the character limit when it has no space). Not empty for an ask with a non-space character."""
    line = " ".join(ask.split())
    if len(line) <= max_chars:
        return line
    room = line[:max_chars - len(ELLIPSIS)]
    if " " in room and not line[len(room)].isspace():
        room = room.rsplit(" ", 1)[0]
    return room.rstrip() + ELLIPSIS
