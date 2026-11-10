"""The bodies of the `site` and `video` kinds, both references the client shows in a frame.

A site piece's body is one https URL, not a YouTube or Vimeo page (a video piece). A video piece's body is a JSON object `{"url": ..., "start": seconds}` (`start`
optional, a whole number of seconds from 0): the URL is a YouTube or Vimeo page, shown through the provider's privacy
embed, or a direct media file (`.mp4`, `.webm`, `.ogv`, `.m4v`, `.mov`). The provider is read from the parsed URL's host
and path, never from prose. An empty body of either kind is a draft. `start` is the video's own place, which a pointer
to the piece can name; when the body has none, a start in the URL (YouTube `t=` or `start=`, Vimeo `#t=`, as seconds or
`1h2m3s`) is the start, and a `start` in the body wins. Whitespace around a body, or around a video's URL, is trimmed
(`trimmed`); whitespace inside a URL refuses it."""

import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from .automation_config import object_of

Provider = Literal["youtube", "vimeo", "file"]

MAX_URL_CHARS = 2000
MAX_START = 359_999
MEDIA_SUFFIXES = (".mp4", ".webm", ".ogv", ".m4v", ".mov")
_YOUTUBE_HOSTS = frozenset(("youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com",
                            "www.youtube-nocookie.com"))
_VIMEO_HOSTS = frozenset(("vimeo.com", "www.vimeo.com", "player.vimeo.com"))
_VIDEO_HOSTS = _YOUTUBE_HOSTS | _VIMEO_HOSTS | {"youtu.be"}
_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_TIME = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", re.ASCII)
_PLAIN_TIME = re.compile(r"(\d+)s?", re.ASCII)
_VIMEO_HASH = re.compile(r"[a-f0-9]{8,16}")
_YOUTUBE_PATHS = ("embed", "shorts", "live", "v")


@dataclass(frozen=True)
class Video:
    """A video piece's body, understood: its `provider`, the `url` as written, the `embed_url` to frame (or, for a
    `file`, to play) with `start` already in it, and `start` in seconds."""

    provider: Provider
    url: str
    embed_url: str
    start: int


def https_host(text: str) -> str | None:
    """The host of `text` when it is one https URL: no whitespace, no credentials, a host, at most `MAX_URL_CHARS`."""
    if not text or len(text) > MAX_URL_CHARS or any(c.isspace() or ord(c) < 32 for c in text):
        return None
    try:
        parts = urlsplit(text)
        host = parts.hostname
        _ = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or not host or parts.username is not None or parts.password is not None:
        return None
    return host.lower()


def trimmed(body: str) -> str:
    """The body of a site piece as it is stored: without the whitespace around it."""
    return body.strip()


def trimmed_video(body: str) -> str:
    """The body of a video piece as it is stored: without the whitespace around it, and its `url` field without any."""
    text = body.strip()
    try:
        fields = object_of(json.loads(text))
    except ValueError:
        return text
    url = None if fields is None else fields.get("url")
    if fields is None or not isinstance(url, str) or url == url.strip():
        return text
    return json.dumps({**fields, "url": url.strip()})


def site_well_formed(body: str) -> bool:
    """Whether `body` is empty or one https URL of a host that is not a video provider's (YouTube and Vimeo refuse to
    be framed as a page; their videos are video pieces)."""
    host = https_host(body.strip())
    return not body.strip() or (host is not None and host not in _VIDEO_HOSTS)


def video_well_formed(body: str) -> bool:
    """Whether `body` is empty or a video of the shape above."""
    return not body.strip() or video_of(body) is not None


def video_of(body: str) -> Video | None:
    """The video `body` holds; None when it is empty or outside the shape above."""
    try:
        fields = object_of(json.loads(body))
    except ValueError:
        return None
    if fields is None or not set(fields) <= {"url", "start"}:
        return None
    url, start = fields.get("url"), fields.get("start")
    if not isinstance(url, str) or (start is not None and (type(start) is not int or not 0 <= start <= MAX_START)):
        return None
    url = url.strip()
    host = https_host(url)
    return None if host is None else _video(url, host, start)


def _video(url: str, host: str, given: int | None) -> Video | None:
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    query = parse_qs(parts.query)
    if host in _YOUTUBE_HOSTS or host == "youtu.be":
        start = given if given is not None else _seconds((query.get("t") or query.get("start") or [""])[0])
        ident = _youtube_id(host, segments, query)
        suffix = f"?start={start}" if start else ""
        embed = f"https://www.youtube-nocookie.com/embed/{ident}{suffix}"
        return Video("youtube", url, embed, start) if ident else None
    if host in _VIMEO_HOSTS:
        found = _vimeo(segments, query)
        if found is None:
            return None
        start = given if given is not None else _seconds(parse_qs(parts.fragment).get("t", [""])[0])
        embed = f"https://player.vimeo.com/video/{found}{f'#t={start}s' if start else ''}"
        return Video("vimeo", url, embed, start)
    if parts.path.lower().endswith(MEDIA_SUFFIXES):
        return Video("file", url, url, given or 0)
    return None


def youtube_id_of(url: str) -> str | None:
    """The id of the YouTube video `url` is the page of (a watch, embed, shorts, live or youtu.be address), read from the
    parsed URL's host and path; None for any other address."""
    host = https_host(url.strip())
    if host is None or (host not in _YOUTUBE_HOSTS and host != "youtu.be"):
        return None
    parts = urlsplit(url.strip())
    return _youtube_id(host, [s for s in parts.path.split("/") if s], parse_qs(parts.query))


def _seconds(text: str) -> int:
    """A time as seconds (`90`, `90s`) or `1h2m3s`; 0 when it is neither or is past `MAX_START`."""
    plain = _PLAIN_TIME.fullmatch(text)
    if plain is not None:
        total = int(plain[1])
    else:
        found = _TIME.fullmatch(text)
        if not text or found is None:
            return 0
        hours, minutes, seconds = (int(g) if g else 0 for g in found.groups())
        total = hours * 3600 + minutes * 60 + seconds
    return total if total <= MAX_START else 0


def _vimeo(segments: list[str], query: dict[str, list[str]]) -> str | None:
    """The player path of a Vimeo URL: `ID`, with `?h=HASH` when it is unlisted (`vimeo.com/ID/HASH`, or `h=` on the
    player URL); None when the ID is not ASCII digits or anything else is left over."""
    rest = segments[1:] if segments[:1] == ["video"] else segments
    if not rest or not (rest[0].isascii() and rest[0].isdecimal()) or len(rest) > 2:
        return None
    unlisted = rest[1] if len(rest) == 2 else (query.get("h") or [None])[0]
    if unlisted is None:
        return rest[0]
    return f"{rest[0]}?h={unlisted}" if _VIMEO_HASH.fullmatch(unlisted) else None


def _youtube_id(host: str, segments: list[str], query: dict[str, list[str]]) -> str | None:
    if host == "youtu.be":
        found = segments[0] if segments else None
    elif segments[:1] == ["watch"]:
        found = (query.get("v") or [None])[0]
    elif len(segments) == 2 and segments[0] in _YOUTUBE_PATHS:
        found = segments[1]
    else:
        found = None
    return found if found is not None and _YOUTUBE_ID.fullmatch(found) else None
