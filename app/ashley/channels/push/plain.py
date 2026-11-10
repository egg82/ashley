"""A reply's `text` as a notification shows it: plain. Her chat Markdown loses its marks, a link keeps its label, and a
list item stays on its own line."""

import re

_FENCE = re.compile(r"^\s*(```|~~~).*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_QUOTE = re.compile(r"^\s{0,3}>\s?")
_BULLET = re.compile(r"^(\s*)[-*+]\s+")
_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\((?:[^()\s]|\([^)\s]*\))*(?:\s+\"[^\"]*\")?\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_STAR_ITALIC = re.compile(r"\*(?=\S)(.+?)(?<=\S)\*")
_UNDERSCORE_ITALIC = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")


def plain_text(markdown: str) -> str:
    """`markdown` without its marks: emphasis and code spans keep their words, a link or image its label, a heading or
    quote its line, a bullet becomes `• `, a fenced block its lines. Text with no Markdown comes back unchanged."""
    lines: list[str] = []
    fenced = False
    for line in markdown.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        elif fenced:
            lines.append(line)
        else:
            lines.append(_inline(_BULLET.sub(r"\1• ", _QUOTE.sub("", _HEADING.sub("", line)))))
    return "\n".join(lines)


def _inline(line: str) -> str:
    line = _IMAGE_OR_LINK.sub(r"\1", line)
    line = _CODE.sub(r"\1", line)
    line = _BOLD.sub(r"\2", line)
    line = _STAR_ITALIC.sub(r"\1", line)
    return _UNDERSCORE_ITALIC.sub(r"\1", line)
