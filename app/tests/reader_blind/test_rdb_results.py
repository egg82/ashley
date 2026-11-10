"""`Results.keep` and `Results.page`, and `read_page` keeping the whole page while its answer stays cut to `page_chars`."""

import asyncio
import json

import httpx2

from ashley.inference.model import ToolCall
from ashley.tools import look_up_config
from ashley.tools.pages import Pages
from ashley.tools.results import ReadPage, Results
from ashley.tools.web_search import WebSearchTools
from page_support import Resolver, html
from search_support import CONFIG as SEARCH, SEARXNG_URL
from search_support import Fake, captured

CONFIG = look_up_config.load()
SEARXNG = captured("searxng")
FIRST = SEARXNG["results"][0]["url"]


def test_a_page_kept_for_a_number_is_the_one_page_returns_whole() -> None:
    store = Results()
    n = store.record("https://example.org/a")
    page = ReadPage("Title", "x" * 50000)
    store.keep(n, page)
    assert store.page(n) == page


def test_a_number_nothing_was_kept_for_has_no_page() -> None:
    store = Results()
    n = store.record("https://example.org/a")
    assert store.page(n) is None and store.page(n + 1) is None and store.page(0) is None and store.page(-1) is None


def test_pages_are_kept_per_number() -> None:
    store = Results()
    a, b, c = (store.record(f"https://example.org/{i}") for i in range(3))
    store.keep(a, ReadPage("A", "aa"))
    store.keep(c, ReadPage("C", "cc"))
    assert store.page(a) == ReadPage("A", "aa") and store.page(b) is None and store.page(c) == ReadPage("C", "cc")


def test_keeping_again_replaces_the_page() -> None:
    store = Results()
    n = store.record("https://example.org/a")
    store.keep(n, ReadPage("old", "old text"))
    store.keep(n, ReadPage("new", "new text"))
    assert store.page(n) == ReadPage("new", "new text")


def test_keeping_a_page_does_not_number_a_result_or_change_its_url() -> None:
    store = Results()
    n = store.record("https://example.org/a")
    nxt = store.next_number()
    store.keep(n, ReadPage("t", "x"))
    assert store.next_number() == nxt and store.url(n) == "https://example.org/a"
    store.keep(n + 10, ReadPage("t", "x"))
    assert store.url(n + 10) is None


def test_a_read_page_holds_a_title_and_text() -> None:
    page = ReadPage("T", "body")
    assert (page.title, page.text) == ("T", "body")


def pages_serving(page_html: str) -> tuple[Pages, Results]:
    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "search.test":
            return httpx2.Response(200, json=SEARXNG)
        return html(page_html) if str(request.url) == FIRST else httpx2.Response(404)

    store = Results()
    client = Fake(answer).client()
    return Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), store), store


def run(pages: Pages, name: str, **arguments: object) -> str:
    got = asyncio.run(pages.call(ToolCall("p", name, arguments)))
    assert not got.is_error, got.content
    return got.content


def first_number(pages: Pages, store: Results) -> int:
    run(pages, "search_web", query="first")
    return next(n for n in range(1, 40) if store.url(n) == FIRST)


def test_read_page_keeps_the_whole_text_while_its_answer_is_cut_to_page_chars() -> None:
    long_text = "word " * (CONFIG.page_chars * 2)
    pages, store = pages_serving(f"<html><head><title>The Title</title></head><body><p>{long_text}</p></body></html>")
    n = first_number(pages, store)
    answer = json.loads(run(pages, "read_page", result=n))
    assert len(answer["text"]) == CONFIG.page_chars
    kept = store.page(n)
    assert kept is not None and "The Title" in kept.title
    assert len(kept.text) > CONFIG.page_chars * 1.5 and kept.text.startswith(answer["text"])


def test_a_result_that_was_searched_but_not_read_has_no_kept_page() -> None:
    pages, store = pages_serving("<p>hello</p>")
    n = first_number(pages, store)
    assert store.page(n) is None
    run(pages, "read_page", result=n)
    assert store.page(n) is not None


def test_a_read_that_fails_keeps_nothing() -> None:
    pages, store = pages_serving("<p>hello</p>")
    first_number(pages, store)
    other = next(n for n in range(1, 40) if store.url(n) not in (None, FIRST))
    got = asyncio.run(pages.call(ToolCall("p", "read_page", {"result": other})))
    assert got.is_error and store.page(other) is None


def test_a_short_page_is_kept_as_it_was_answered() -> None:
    pages, store = pages_serving("<html><head><title>Short</title></head><body><p>just a little text</p></body></html>")
    n = first_number(pages, store)
    answer = json.loads(run(pages, "read_page", result=n))
    kept = store.page(n)
    assert kept is not None and answer["text"] in kept.text and "just a little text" in kept.text
