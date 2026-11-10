"""A page's readable text from its HTML, with the standard library's `html.parser`: what a person would read, without
the scripts, styles and the page's chrome (navigation, header, footer, forms)."""

import re
from html.parser import HTMLParser

SKIPPED = frozenset({"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "template"})
BLOCKS = frozenset({"address", "article", "blockquote", "br", "dd", "div", "dl", "dt", "fieldset", "figcaption",
                    "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "main", "ol", "p", "pre", "section",
                    "table", "td", "th", "title", "tr", "ul"})
_SPACES = re.compile(r"[^\S\n]+")


def title_of(html: str) -> str:
    """The page's own title: the text of its first `<title>`, whitespace collapsed; empty when it has none."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    return " ".join(parser.title.split())


def text_of(html: str) -> str:
    """The text of `html`: the contents of the `SKIPPED` elements dropped, each block element on its own line,
    whitespace collapsed to single spaces, blank lines dropped, entities unescaped."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = (_SPACES.sub(" ", line).strip() for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line in lines if line)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._titled = False
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and not self.title and not self._skipping:
            self._titled = True
        if tag in SKIPPED:
            self._skipping += 1
        elif tag in BLOCKS and not self._skipping:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._titled = False
        if tag in SKIPPED:
            self._skipping = max(0, self._skipping - 1)
        elif tag in BLOCKS and not self._skipping:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCKS and not self._skipping:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._titled:
            self.title += data
        if not self._skipping:
            self.parts.append(data.replace("\n", " "))
