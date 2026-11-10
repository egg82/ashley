"""A reader piece's body (kind `reader`, format `reader`): a web page's text as she read it, with where it came from.
One JSON object of `url` (an https URL, as `embed.https_host` judges it, or empty for text that came from no
page: a recording's transcript), `title` (the page's own, possibly
empty) and `text` (the page's readable text, lines separated by `\\n`), and, for a transcript only, `recording`: the id
of the piece it was made from and the second each line (paragraph) starts at. An empty body is a draft and passes.

A passage is a location in this piece's own terms: a paragraph, which is one line of `text`, and a range of characters
inside it (`start` up to `end`, counted in Unicode code points, `start < end`). Lines are stored, so a passage means the
same text however a screen lays the page out."""

import json
import math
from dataclasses import dataclass
from typing import Any

from .automation_config import object_of
from .embed import https_host

_FIELDS = frozenset(("url", "title", "text"))
_FIELDS_WITH_RECORDING = _FIELDS | {"recording"}


@dataclass(frozen=True)
class Passage:
    """Characters `start` to `end` of paragraph `paragraph` (0 first)."""

    paragraph: int
    start: int
    end: int


@dataclass(frozen=True)
class Recording:
    """The piece a transcript was made from and the second each of its lines starts at, in line order."""

    piece_id: int
    starts: tuple[float, ...]


@dataclass(frozen=True)
class Page:
    """A reader piece's body, understood. `recording` is None for a page, and for a transcript whose lines no longer
    number its `starts` (it was edited), since a time then belongs to no line."""

    url: str
    title: str
    text: str
    recording: Recording | None = None

    @property
    def paragraphs(self) -> tuple[str, ...]:
        return tuple(self.text.split("\n"))


def body_of(url: str, title: str, text: str, recording: Recording | None = None) -> str:
    """The body of a reader piece holding `text` read from `url`, or the transcript of `recording`."""
    body: dict[str, object] = {"url": url, "title": title, "text": text}
    if recording is not None:
        body["recording"] = {"piece_id": recording.piece_id, "starts": list(recording.starts)}
    return json.dumps(body, ensure_ascii=False)


def _recording_of(raw: object, lines: int) -> Recording | None:
    """The recording `raw` names; None when it is not of the shape above or its `starts` do not number `lines`."""
    loaded = object_of(raw)
    if loaded is None or frozenset(loaded) != frozenset(("piece_id", "starts")):
        return None
    piece_id = loaded["piece_id"]
    loose: Any = loaded["starts"]
    if type(piece_id) is not int or not isinstance(loaded["starts"], list):
        return None
    starts = list[object](loose)
    times = tuple(float(str(t)) for t in starts if type(t) in (int, float) and math.isfinite(float(str(t))) and float(str(t)) >= 0)
    return Recording(piece_id, times) if len(times) == len(starts) == lines else None


def page_of(body: str) -> Page | None:
    """The page `body` holds; None when it is empty or not of the shape above."""
    try:
        loaded = object_of(json.loads(body))
    except ValueError:
        return None
    if loaded is None or frozenset(loaded) not in (_FIELDS, _FIELDS_WITH_RECORDING):
        return None
    url, title, text = loaded["url"], loaded["title"], loaded["text"]
    if not isinstance(url, str) or (url and https_host(url) is None) or not isinstance(title, str) or not isinstance(text, str):
        return None
    recording = _recording_of(loaded["recording"], len(text.split("\n"))) if "recording" in loaded else None
    return Page(url, title, text, recording)


def well_formed(body: str) -> bool:
    """Whether `body` is empty or a page of the shape above."""
    return not body.strip() or page_of(body) is not None


def holds(page: Page, passage: Passage) -> bool:
    """Whether `passage` is a non-empty range inside one of `page`'s paragraphs."""
    paragraphs = page.paragraphs
    if not 0 <= passage.paragraph < len(paragraphs):
        return False
    return 0 <= passage.start < passage.end <= len(paragraphs[passage.paragraph])


def locate(page: Page, quote: str) -> Passage | None:
    """The one place `quote` occurs in `page`'s text, inside a single paragraph; None when it occurs nowhere, more
    than once, or only across a line break, or is empty."""
    found: list[Passage] = []
    if not quote:
        return None
    for index, paragraph in enumerate(page.paragraphs):
        at = paragraph.find(quote)
        while at >= 0:
            found.append(Passage(index, at, at + len(quote)))
            at = paragraph.find(quote, at + 1)
    return found[0] if len(found) == 1 else None
