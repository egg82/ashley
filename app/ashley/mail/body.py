"""A message's text and attachments from Gmail's MIME tree: the plain parts when there are any, else the HTML parts
turned to text."""

import base64
import binascii
from html.parser import HTMLParser

from ..text import without_nul
from .gmail_shapes import Part
from .model import Attachment

_BREAKS = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table"})
_SKIPPED = frozenset({"script", "style", "head"})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skipping += 1
        elif tag in _BREAKS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skipping = max(0, self._skipping - 1)
        elif tag in _BREAKS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.chunks.append(data)


def html_text(html: str) -> str:
    """`html` as text: tags dropped, script and style content with them, block ends as line breaks, blank runs
    collapsed."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.chunks).splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def _charset(part: Part) -> str:
    for header in part.headers:
        if header.name.lower() == "content-type":
            for piece in header.value.split(";")[1:]:
                key, _, value = piece.strip().partition("=")
                if key.lower() == "charset" and value:
                    return value.strip('"').lower()
    return "utf-8"


def _decoded(part: Part) -> str:
    try:
        raw = base64.urlsafe_b64decode(part.body.data + "=" * (-len(part.body.data) % 4))
    except (binascii.Error, ValueError):
        return ""
    try:
        return raw.decode(_charset(part), errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _walk(part: Part, plain: list[str], html: list[str], files: list[Attachment]) -> None:
    if part.filename:
        files.append(Attachment(part.filename, part.mimeType, part.body.size))
    elif part.mimeType == "text/plain" and part.body.data:
        plain.append(_decoded(part))
    elif part.mimeType == "text/html" and part.body.data:
        html.append(_decoded(part))
    for child in part.parts:
        _walk(child, plain, html, files)


def text_and_attachments(payload: Part) -> tuple[str, tuple[Attachment, ...]]:
    """The body of a message as text, and its attachments by name, type and size."""
    plain: list[str] = []
    html: list[str] = []
    files: list[Attachment] = []
    _walk(payload, plain, html, files)
    text = "\n".join(plain) if plain else "\n".join(html_text(h) for h in html)
    return without_nul(text, "mail").strip(), tuple(files)
