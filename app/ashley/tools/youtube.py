"""What a YouTube watch page publishes, read from its `ytInitialPlayerResponse` JSON: the video's title, channel, publish
date, length and description. The page's HTML text holds none of it, since it is all inside a script. Pure; `pages` fetches."""

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from ..runs.captions import stamp
from . import page_fetch
from .results import Results

WATCH = "https://www.youtube.com/watch?v="
BROWSER = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}
_LINK = re.compile(r"https://[^\s<>\"')\]]+")
_ASSIGNED = re.compile(r"ytInitialPlayerResponse\s*=\s*(?=\{)")


def player_response(html: str) -> Mapping[str, Any] | None:
    """The player-response object a watch page assigns to `ytInitialPlayerResponse`; None when the page has none, or it was cut
    off before the object ended."""
    assigned = _ASSIGNED.search(html)
    if assigned is None:
        return None
    try:
        found, _ = json.JSONDecoder().raw_decode(html, assigned.end())
    except ValueError:
        return None
    return _mapping(found) or None


Link = Callable[[str], int | None]


class Links:
    """Numbers the links of a video's description into the turn's `Results`, each once, at most `limit` of them; past
    that a link stays plain."""

    def __init__(self, numbered: Results, limit: int) -> None:
        self._numbered = numbered
        self._limit = limit
        self._linked: dict[str, int] = {}

    def __call__(self, url: str) -> int | None:
        if url not in self._linked and len(self._linked) < self._limit:
            self._linked[url] = self._numbered.record(url)
        return self._linked.get(url)


def details_text(player: Mapping[str, Any], link: Link) -> str | None:
    """The video's title, channel, publish date, length and description as lines of text; None without a title. Each https
    link in the description is followed by `(result N)` when `link` gives it the number N, None leaving it plain."""
    details = _mapping(player.get("videoDetails"))
    micro = _mapping(_mapping(player.get("microformat")).get("playerMicroformatRenderer"))
    title = _text(details.get("title"))
    if not title:
        return None
    lines = [f"Title: {title}"]
    for label, value in (("Channel", _text(details.get("author"))), ("Published", _text(micro.get("publishDate"))[:10]),
                         ("Length", _length(details.get("lengthSeconds")))):
        if value:
            lines.append(f"{label}: {value}")
    description = _numbered(_text(details.get("shortDescription")).strip(), link)
    return "\n".join(lines) + (f"\nDescription:\n{description}" if description else "")


def _numbered(description: str, link: Link) -> str:
    def mark(found: re.Match[str]) -> str:
        url = found[0].rstrip(".,;:!?")
        number = link(url)
        return found[0] if number is None else f"{url} (result {number}){found[0][len(url):]}"
    return _LINK.sub(mark, description)


def read_page(source: page_fetch.Source, link: Link) -> page_fetch.Page:
    """The page of a watch-page `source` as `read_page` returns it: the video's details (see `details_text`), else (a page
    without a player response) the page's text as any page's."""
    player = player_response(source.text) if source.kind == "text/html" else None
    text = None if player is None else details_text(player, link)
    if player is None or text is None:
        return page_fetch.page_of(source, None)
    return page_fetch.Page(text, source.bytes, _text(_mapping(player.get("videoDetails")).get("title")))


def _mapping(value: object) -> Mapping[str, Any]:
    loose: Any = value
    return dict[str, Any](loose) if isinstance(value, dict) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _length(value: object) -> str:
    seconds = value if isinstance(value, str) and value.isdecimal() else ""
    return stamp(int(seconds))[1:-1] if seconds else ""
