"""The web search results one turn has numbered, each number's URL: the one store `search_web` records into and
`read_page` and the bench tools read from, so a page or a bench reference is always one a search returned this turn, or
the address a site or video piece stores (`bench_page`), and never a URL she wrote. A turn makes one `Results` (`channels.landing.Landing`) and `bound`s it while a tool call runs,
so the look-ups inside that call (`pages.Pages`) number into it, each continuing from the last; a call outside any turn
sees a store of its own that nothing else reads."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from ..workshop.recipe import Recipe


@dataclass(frozen=True)
class ReadPage:
    """A page `read_page` or `bench_read_piece` read: its own `title` and its whole extracted `text`, of which she was given the first
    `page_chars`; a reader piece holds all of it. `cut` is set when the body was longer than `page_bytes` and so the
    text ends early. `recipe` is the recipe the page publishes, which a recipe piece holds; None when it publishes none."""

    title: str
    text: str
    cut: bool = False
    recipe: Recipe | None = None


class Results:
    def __init__(self) -> None:
        self._urls: dict[int, str] = {}
        self._pages: dict[int, ReadPage] = {}

    def record(self, url: str) -> int:
        """The next number, from 1, now meaning `url`."""
        number = len(self._urls) + 1
        self._urls[number] = url
        return number

    def next_number(self) -> int:
        """The number the next result recorded gets."""
        return len(self._urls) + 1

    def keep(self, number: int, page: ReadPage) -> None:
        """Result `number`'s page as she read it this turn, for a reader piece to hold."""
        self._pages[number] = page

    def page(self, number: int) -> ReadPage | None:
        """The page read for result `number` this turn; None when it was not read."""
        return self._pages.get(number)

    def url(self, number: int) -> str | None:
        """The URL result `number` was; None when no result has that number."""
        return self._urls.get(number)


_BOUND: ContextVar[Results | None] = ContextVar("ashley_results", default=None)


def current() -> Results:
    """The store bound to this call, else a new one."""
    return _BOUND.get() or Results()


@contextmanager
def bound(results: Results) -> Generator[None]:
    """`current` is `results` inside the block."""
    token = _BOUND.set(results)
    try:
        yield
    finally:
        _BOUND.reset(token)
