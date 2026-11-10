"""The page a site or video piece shows, read for `bench_read_piece`. The address is the one the piece stores, written by
the server from a result or given by a person, never typed by the model, so reading it plants nothing. A video's page is
its details and a description's links come numbered into the turn's `Results`, as `read_page` gives them. The page
itself is numbered and kept there too, recipe included, so a reader, code, document or recipe piece goes up from it by
that number as from a page `read_page` read."""

import logging
import time

from .. import logs, services
from ..workshop import embed
from ..workshop.model import Piece
from ..workshop.rules import Rules
from . import page_fetch, page_reader, youtube
from .look_up_config import LookUpConfig
from .pages import MAX_LINKS, kept
from .results import Results

log = logging.getLogger("ashley.tools")


def address_of(piece: Piece, rules: Rules) -> str | None:
    """The address of site or video piece `piece`; None for any other piece, an empty draft, or a video file."""
    kind = rules.kinds.get(piece.kind)
    if kind is None or kind.format not in ("site", "video"):
        return None
    if kind.format == "site":
        return piece.text.body.strip() or None
    video = embed.video_of(piece.text.body)
    return None if video is None or video.provider == "file" else video.url


async def page_text(piece: Piece, rules: Rules, numbered: Results, config: LookUpConfig,
                    chars: int) -> tuple[int, str] | None:
    """The result number `numbered` now gives the page `piece` shows, kept as read, and the first `chars` characters of
    its text; None when it shows none or the page cannot be read. Logs `bench.page` with the outcome, the characters and
    the links numbered, never the address or the text."""
    url = address_of(piece, rules)
    if url is None:
        return None
    started = time.monotonic()
    before = numbered.next_number()
    limits = page_reader.limits_of(config)
    try:
        page = await services.get(page_reader.PageReader).read(url, limits, youtube.Links(numbered, MAX_LINKS))
    except page_fetch.Refused:
        return _logged(piece, started, "refused", None, 0)
    except page_fetch.NoPage:
        return _logged(piece, started, "unavailable", None, 0)
    links = numbered.next_number() - before
    number = numbered.record(url)
    numbered.keep(number, kept(page, limits))
    return _logged(piece, started, "ok", (number, page.text[:chars]), links)


def _logged(piece: Piece, started: float, outcome: str, read: tuple[int, str] | None,
            links: int) -> tuple[int, str] | None:
    logs.info(log, "bench.page", piece=piece.id, outcome=outcome, chars=0 if read is None else len(read[1]),
              links=links, duration_ms=int((time.monotonic() - started) * 1000))
    return read
