"""Timestamped text of a recording, as lines `[m:ss] text` (or `[h:mm:ss]` from an hour), and the parsing of captions
(SubRip, WebVTT) into them. Pure."""

import re
from dataclasses import dataclass

_CUE_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->")
_TAG = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class Segment:
    """`text` spoken from `start` seconds."""

    start: float
    text: str


def stamp(seconds: float) -> str:
    """`[m:ss]`, or `[h:mm:ss]` from an hour on, of `seconds` rounded down."""
    whole = int(max(0, seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"[{hours}:{minutes:02d}:{secs:02d}]" if hours else f"[{minutes}:{secs:02d}]"


def spoken(segments: list[Segment]) -> list[Segment]:
    """The segments that have text, which are the ones `lines_of` writes, in its order."""
    return [s for s in segments if s.text.strip()]


def lines_of(segments: list[Segment]) -> str:
    """One line per segment, stamped; segments with no text are left out, and line breaks inside a text become spaces."""
    return "\n".join(f"{stamp(s.start)} {' '.join(s.text.split())}" for s in spoken(segments))


def parse_captions(text: str) -> list[Segment]:
    """The cues of SubRip or WebVTT `text`, in file order, each with the time it starts and its words (markup tags
    dropped, lines joined by a space). Text that holds no cue gives []."""
    segments: list[Segment] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")):
        rows = block.strip().split("\n")
        for at, row in enumerate(rows):
            found = _CUE_TIME.match(row)
            if found:
                hours, minutes, secs, millis = found.groups()
                start = int(hours or 0) * 3600 + int(minutes) * 60 + int(secs) + int(millis.ljust(3, "0")) / 1000
                words = " ".join(_TAG.sub("", " ".join(rows[at + 1:])).split())
                if words:
                    segments.append(Segment(start, words))
                break
    return segments
