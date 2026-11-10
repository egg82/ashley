"""A page whose site refuses the plain fetch with a refusing status is read in the page browser, when one is wired, and
read like any page (its text and its recipe); any other failure, an unwired browser, or a browser that is refused too,
leaves the page unread as before. The log line carries the outcome and status, never the address."""

import asyncio
from dataclasses import dataclass, field

import pytest
from ashley import logs, services
from ashley.looks.browser import Browsed, BrowseUnavailable, PageBrowser
from ashley.tools import page_fetch, page_reader, youtube
from ashley.tools.page_reader import FetchedPageReader
from ashley.tools.results import Results
from page_support import Resolver, html, site
from recipe_support import MASH, page_of
from search_support import events

LIMITS = page_fetch.Limits(timeout_s=6, max_redirects=3, max_bytes=1_000_000)
URL = "https://recipes.example/mash"


@dataclass
class FakeBrowser(PageBrowser):
    """Answers every read with `answer`, or raises `fails`; `asked` is each address read."""

    answer: Browsed | None = None
    fails: str | None = None
    asked: list[str] = field(default_factory=list[str])

    def reads(self) -> bool:
        return True

    async def read(self, url: str) -> Browsed:
        self.asked.append(url)
        if self.fails is not None:
            raise BrowseUnavailable(self.fails)
        assert self.answer is not None
        return self.answer


def browsed(text: str, status: int = 200, kind: str = "text/html") -> Browsed:
    return Browsed(status, kind, text, len(text.encode()), False)


def read(status: int, browser: PageBrowser | None) -> page_fetch.Page:
    if browser is not None:
        services.register(PageBrowser, browser)
    reader = FetchedPageReader(site({URL: html("<p>Just a moment</p>", status=status)}).client(), Resolver())
    return asyncio.run(reader.read(URL, LIMITS, youtube.Links(Results(), 5)))


@pytest.mark.parametrize("status", sorted(page_reader.REFUSING))
def test_a_refused_fetch_is_read_in_the_browser_with_its_recipe(status: int) -> None:
    browser = FakeBrowser(browsed(page_of(MASH)))
    page = read(status, browser)
    assert browser.asked == [URL]
    assert page.recipe is not None and page.recipe.url == URL
    assert page.recipe.name == "Garlic Yukon Gold Mashed Potatoes"
    assert "Jump to recipe" in page.text


def test_a_page_that_is_not_there_is_not_sent_to_the_browser() -> None:
    browser = FakeBrowser(browsed(page_of(MASH)))
    with pytest.raises(page_fetch.Status):
        read(404, browser)
    assert browser.asked == []


def test_with_no_browser_wired_the_refusal_stands() -> None:
    with pytest.raises(page_fetch.Status) as refused:
        read(403, None)
    assert refused.value.status == 403


def test_a_browser_that_is_refused_too_leaves_the_page_unread() -> None:
    with pytest.raises(page_fetch.Status) as refused:
        read(403, FakeBrowser(browsed("<title>Just a moment...</title>", status=403)))
    assert refused.value.status == 403


def test_a_browser_that_cannot_run_is_no_page() -> None:
    with pytest.raises(page_fetch.NoPage):
        read(403, FakeBrowser(fails="never_ran"))


def test_a_browsed_answer_that_is_not_text_is_refused() -> None:
    with pytest.raises(page_fetch.Refused):
        read(403, FakeBrowser(browsed("%PDF", kind="application/pdf")))


def test_the_browsed_line_names_no_address(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    read(403, FakeBrowser(browsed(page_of(MASH))))
    out = capsys.readouterr().out
    (line,) = events(out, "page.browsed")
    assert line["outcome"] == "ok" and line["status"] == "200"
    assert "recipes.example" not in out
