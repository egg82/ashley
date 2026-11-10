"""`read_page` on a YouTube video's page returns the video's details from the page's player response. The request names a
browser and a language, only the id of the video goes into it, and a look-alike address is read as any page."""

import asyncio
import json

import httpx2

from ashley.inference.model import ToolCall
from ashley.tools import look_up_config
from ashley.tools.pages import MAX_LINKS, Pages
from ashley.tools.results import Results
from ashley.tools.web_search import WebSearchTools
from page_support import Resolver, html
from search_support import CONFIG as SEARCH, SEARXNG_URL
from youtube_read_support import VIDEO, WATCH, WATCH_HTML, PLAYER, youtube

CONFIG = look_up_config.load()


def read(address: str, pages: dict[str, httpx2.Response], resolver: Resolver | None = None) -> tuple[dict[str, object], list[httpx2.Request]]:
    fake = youtube(pages)
    client = fake.client()
    numbered = Results()
    numbered.record(address)
    got = asyncio.run(Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, resolver or Resolver(), numbered)
                      .call(ToolCall("p1", "read_page", {"result": 1})))
    assert not got.is_error, got.content
    body: dict[str, object] = json.loads(got.content)
    return body, fake.requests


def test_a_watch_page_reads_as_the_video_details_with_its_description() -> None:
    body, requests = read(WATCH + "&t=30s", {WATCH: html(WATCH_HTML)})
    text = str(body["text"])
    assert text.startswith("Title: I Found a Bug in the Bread Investigation\nChannel: Loaf Lab\n")
    assert PLAYER["videoDetails"]["shortDescription"].strip().split("\n")[0] in text
    assert [str(r.url) for r in requests] == [WATCH]
    assert requests[0].headers["user-agent"] == "Mozilla/5.0" and requests[0].headers["accept-language"] == "en"


def test_a_short_address_is_fetched_as_the_watch_page_of_its_id() -> None:
    _, requests = read(f"https://youtu.be/{VIDEO}?si=tracking", {WATCH: html(WATCH_HTML)})
    assert [str(r.url) for r in requests] == [WATCH]


def test_the_details_are_cut_to_page_chars_like_any_page() -> None:
    long = WATCH_HTML.replace("Music: Morning Rise", "x" * 7000 + " Music: Morning Rise")
    body, _ = read(WATCH, {WATCH: html(long)})
    assert len(str(body["text"])) == CONFIG.page_chars


def test_a_link_in_the_description_gets_a_result_number_that_read_page_then_follows() -> None:
    other = "https://www.youtube.com/watch?v=Qw3rTy7UiOp"
    fake = youtube({WATCH: html(WATCH_HTML), other: html("<p>other</p>")})
    client = fake.client()
    numbered = Results()
    numbered.record(WATCH)
    pages = Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), numbered)
    first = json.loads(asyncio.run(pages.call(ToolCall("p1", "read_page", {"result": 1}))).content)
    assert f"{other}&t=531s (result 2)" in first["text"] and numbered.url(2) == f"{other}&t=531s"
    second = asyncio.run(pages.call(ToolCall("p2", "read_page", {"result": 2})))
    assert not second.is_error and [str(r.url) for r in fake.requests] == [WATCH, other]


def test_a_video_read_twice_numbers_each_link_once_and_only_up_to_the_cap() -> None:
    links = " ".join(f"https://a.example/{n}" for n in range(MAX_LINKS + 5))
    page = WATCH_HTML.replace("Music: Morning Rise", links + " Music: Morning Rise")
    fake = youtube({WATCH: html(page)})
    client = fake.client()
    numbered = Results()
    numbered.record(WATCH)
    pages = Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), numbered)
    for _ in range(2):
        asyncio.run(pages.call(ToolCall("p1", "read_page", {"result": 1})))
    assert numbered.next_number() == MAX_LINKS + 2 and numbered.url(MAX_LINKS + 1) == f"https://a.example/{MAX_LINKS - 2}"


def test_an_address_that_only_mentions_youtube_is_read_as_any_page() -> None:
    address = f"https://clinic.example/watch?v={VIDEO}"
    body, requests = read(address, {address: html("<p>hours</p>")})
    assert body["text"] == "hours" and [str(r.url) for r in requests] == [address]
    assert "user-agent" not in requests[0].headers or requests[0].headers["user-agent"] != "Mozilla/5.0"
