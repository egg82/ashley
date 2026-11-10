"""A turn she kept to herself: her stored `QUIET` turn, and the turn it answers. Nothing was said, so a page shows neither
and a list of conversations counts neither (`postgres_listing`)."""

from collections.abc import Sequence

from .model import Turn

QUIET = "(She stayed quiet.)"


def shown(turns: Sequence[Turn]) -> list[Turn]:
    """`turns` without the ones she kept to herself and the turns they answer."""
    quiet = {t.id: t.answers for t in turns if t.author == "ashley" and t.text == QUIET}
    hidden = quiet.keys() | {a for a in quiet.values() if a is not None}
    return [t for t in turns if t.id not in hidden]
