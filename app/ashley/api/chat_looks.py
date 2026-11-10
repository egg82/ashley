"""Which of her turns shows which looks. A look is recorded against the person's turn that asked; the page shows it under
her final answer to that turn (the turn of hers recording that it answers it), not under a held line. Its picture is
reached by a picture link (`ashley.looks.links`), shown in place."""

import time
from collections.abc import Sequence

from ..conversations.answers import answer_of
from ..conversations.model import Turn
from ..files import config as files_config
from ..files.links import window_end
from ..looks import links as look_links
from ..looks.looks import Look
from .look_models import ChatLook

CONFIG = files_config.load()


def wire(look: Look, key: bytes, now: float) -> ChatLook:
    """`look` for the page; its link is minted under `key` (empty: none) to end with the current half-window of the
    files' `link_ttl_s` (as a bench's file links do, so the page keeps the picture) after `now`."""
    if not key:
        return ChatLook(id=look.id, bench_id=look.bench_id, piece_id=look.piece_id, media_type=look.media_type,
                        url=None, expires_at=None)
    ends = window_end(now, CONFIG.link_ttl_s)
    token = look_links.mint_picture(key, look_links.Picture(look.household_id, look.sha256, look.media_type, ends))
    return ChatLook(id=look.id, bench_id=look.bench_id, piece_id=look.piece_id, media_type=look.media_type,
                    url=look_links.PICTURE_PATH + token, expires_at=ends)


def under_answers(turns: Sequence[Turn], looks: Sequence[Look], key: bytes,
                  now: float | None = None) -> dict[int, list[ChatLook]]:
    """The looks to show under each turn of hers, keyed by its id, in the order she took them. A look whose person turn
    has no answer yet, or is not among `turns`, is under none."""
    answers = answer_of(turns)
    moment = time.time() if now is None else now
    shown: dict[int, list[ChatLook]] = {}
    for look in sorted(looks, key=lambda x: x.id):
        under = answers.get(look.turn_id)
        if under is not None:
            shown.setdefault(under, []).append(wire(look, key, moment))
    return shown
