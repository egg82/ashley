"""`Pages`, one look-up's web search and the pages it may read: results numbered across the look-up, `read_page` by
number only, at most two reads, and the outcomes and log line of a read. The look-up making one for each call is
tested at the end, through `LookUpTools`."""

import asyncio
import json
from typing import Any

import httpx2
import pytest

from ashley import logs, services
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolCalls, ToolResult, ToolResults
from ashley.tools import look_up_config
from ashley.tools.look_up import LookedUp, LookUpTools
from ashley.tools.pages import Pages
from ashley.tools.results import Results, bound
from ashley.tools.web_search import WebSearchTools
from page_support import PAGE_HTML, Resolver, html
from respond_support import FakeInference
from search_support import CONFIG as SEARCH, SEARXNG_URL, Fake, captured, events

CONFIG = look_up_config.load()
SEARXNG = captured("searxng")
SECOND = {"results": [{**r, "url": r["url"].replace("https://", "https://second.")} for r in SEARXNG["results"]]}
PAGE = "https://www.almanac.com/content/when-daylight-saving-time"   # the first search's fourth result


def serve(pages: dict[str, httpx2.Response] | None = None) -> Fake:
    """SearXNG answers query `second` with SECOND and any other with the capture; other URLs are `pages`."""
    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "search.test":
            return httpx2.Response(200, json=SECOND if request.url.params["q"] == "second" else SEARXNG)
        return (pages or {}).get(str(request.url), httpx2.Response(404))
    return Fake(answer)


def make(fake: Fake, resolver: Resolver | None = None, config: look_up_config.LookUpConfig = CONFIG) -> Pages:
    client = fake.client()
    return Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, config, resolver or Resolver())


def run(pages: Pages, name: str, **arguments: object) -> ToolResult:
    return asyncio.run(pages.call(ToolCall("p1", name, arguments)))


def results(result: ToolResult) -> list[dict[str, Any]]:
    assert not result.is_error
    shown: list[dict[str, Any]] = json.loads(result.content)["results"]
    return shown


def test_the_catalogue_is_the_web_search_and_read_page_by_number() -> None:
    catalogue = asyncio.run(make(serve()).catalogue())
    assert [s.name for s in catalogue.specs] == ["search_web", "read_page"]
    read = catalogue.specs[1]
    properties: Any = read.parameters["properties"]
    assert read.parameters["required"] == ["result"] and set(properties) == {"result"}
    assert properties["result"]["type"] == "integer"
    assert "snippet does not answer" in read.description and "url" not in json.dumps(read.parameters).lower()


def test_numbers_run_on_across_searches_in_one_look_up() -> None:
    pages = make(serve())
    first = results(run(pages, "search_web", query="first"))
    second = results(run(pages, "search_web", query="second"))
    assert [r["result"] for r in first] == [1, 2, 3, 4, 5]
    assert [r["result"] for r in second] == [6, 7, 8, 9, 10]
    assert second[0]["source"] == "second.www.timeanddate.com"


def test_a_failed_search_takes_no_numbers() -> None:
    fake = Fake(lambda r: httpx2.Response(500) if r.url.params["q"] == "down" else httpx2.Response(200, json=SEARXNG))
    pages = make(fake)
    assert run(pages, "search_web", query="down").is_error
    assert run(pages, "search_web", query="up").content.count('"result": 1,') == 1


def test_each_pages_numbers_from_one() -> None:
    fake = serve()
    run(make(fake), "search_web", query="first")
    assert results(run(make(fake), "search_web", query="second"))[0]["result"] == 1


def test_read_page_fetches_the_url_behind_the_number() -> None:
    fake = serve({PAGE: html(PAGE_HTML), "https://second.www.timeanddate.com/time/change/usa": html("<p>later</p>")})
    pages = make(fake)
    run(pages, "search_web", query="first")
    run(pages, "search_web", query="second")
    got = run(pages, "read_page", result=4)
    assert not got.is_error and got.call_id == "p1"
    body = json.loads(got.content)
    assert set(body) == {"result", "text"} and body["result"] == 4 and "Sun8:00am - 5:00pm" in body["text"]
    assert json.loads(run(pages, "read_page", result=6).content) == {"result": 6, "text": "later"}
    assert [str(r.url) for r in fake.requests[2:]] == [PAGE, "https://second.www.timeanddate.com/time/change/usa"]


def test_the_text_is_cut_to_page_chars() -> None:
    pages = make(serve({PAGE: html("<p>" + "x" * (CONFIG.page_chars + 500) + "</p>")}))
    run(pages, "search_web", query="first")
    assert json.loads(run(pages, "read_page", result=4).content)["text"] == "x" * CONFIG.page_chars


@pytest.mark.parametrize("arguments", [{}, {"result": "4"}, {"result": 4.0}, {"result": True}, {"result": None},
                                       {"url": PAGE}])
def test_anything_but_an_integer_result_is_an_error(arguments: dict[str, object]) -> None:
    fake = serve({PAGE: html("<p>x</p>")})
    pages = make(fake)
    run(pages, "search_web", query="first")
    got = asyncio.run(pages.call(ToolCall("p1", "read_page", arguments)))
    assert got.is_error and got.content == "read_page needs a result number" and len(fake.requests) == 1


@pytest.mark.parametrize("number", [0, -1, 6, 99])
def test_a_number_this_look_up_never_returned_is_an_error(number: int) -> None:
    fake = serve()
    pages = make(fake)
    run(pages, "search_web", query="first")
    got = run(pages, "read_page", result=number)
    assert got.is_error and got.content == "no search result with that number" and len(fake.requests) == 1


def test_before_any_search_no_number_is_known() -> None:
    got = run(make(serve()), "read_page", result=1)
    assert got.is_error and got.content == "no search result with that number"


def test_a_third_read_is_refused_without_a_fetch() -> None:
    fake = serve({PAGE: html("<p>x</p>")})
    pages = make(fake)
    run(pages, "search_web", query="first")
    run(pages, "read_page", result=4)
    run(pages, "read_page", result=1)
    got = run(pages, "read_page", result=4)
    assert got.is_error and got.content == "two pages already read"
    assert len(fake.requests) == 3


@pytest.mark.parametrize(("fake", "resolver", "outcome", "reason"), [
    (serve({PAGE: html("<p>x</p>")}), Resolver({"www.almanac.com": ["10.0.0.3"]}), "refused", "that page cannot be read"),
    (serve({PAGE: html(b"%PDF", kind="application/pdf")}), None, "refused", "that page cannot be read"),
    (serve(), None, "unavailable", "the page did not answer")])
def test_a_page_that_cannot_be_read_says_so_without_the_url(fake: Fake, resolver: Resolver | None, outcome: str,
                                                           reason: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    pages = make(fake, resolver)
    run(pages, "search_web", query="first")
    capsys.readouterr()
    got = run(pages, "read_page", result=4)
    assert got.is_error and got.content == reason
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"], line["bytes"], line["chars"]) == ("read_page", outcome, "0", "0")


def test_the_log_carries_bytes_and_chars_never_the_url_host_or_text(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    page = "<p>PLANTED-TEXT-zq " + "y" * 7000 + "</p>"
    pages = make(serve({PAGE: html(page)}))
    run(pages, "search_web", query="first")
    capsys.readouterr()
    run(pages, "read_page", result=4)
    out = capsys.readouterr().out
    (line,) = events(out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("read_page", "ok")
    assert line["bytes"] == str(len(page)) and line["chars"] == str(CONFIG.page_chars) and "duration_ms" in line
    assert "PLANTED" not in out and "almanac" not in out and "daylight" not in out


def test_a_look_up_makes_its_own_pages_and_offers_read_page_only_inside(capsys: pytest.CaptureFixture[str]) -> None:
    fake = serve({PAGE: html("<p>a \"quoted\" line</p>" * 2000)})
    made: list[Pages] = []

    def sources() -> Pages:
        made.append(make(fake))
        return made[-1]

    model = FakeInference()
    model.script = [ToolCalls((ToolCall("s1", "search_web", {"query": "first"}),)),
                    ToolCalls((ToolCall("r1", "read_page", {"result": 4}),)),
                    LookedUp(found=True, answer="a", sources=["almanac.com"], references=[])]
    services.register(Inference, model)
    try:
        tools = LookUpTools(sources, CONFIG)
        assert [s.name for s in asyncio.run(tools.catalogue()).specs] == ["look_up"]
        asyncio.run(tools.call(ToolCall("q1", "look_up", {"question": "q", "now": "Tuesday"})))
    finally:
        services.unregister(Inference)
    assert len(made) == 2 and made[0] is not made[1]
    assert [s.name for s in model.prompts[0].tools] == ["search_web", "read_page"]
    read = model.prompts[2].messages[-1]
    assert isinstance(read, ToolResults)
    assert json.loads(read.results[0].content)["text"] == ("a \"quoted\" line\n" * 2000)[:CONFIG.page_chars]


def test_a_turns_look_ups_number_into_one_store_that_names_each_result_url() -> None:
    store = Results()
    fake = serve()
    with bound(store):
        first, second = make(fake), make(fake)
    results(run(first, "search_web", query="first"))
    later = results(run(second, "search_web", query="second"))
    assert [r["result"] for r in later] == [6, 7, 8, 9, 10]
    assert store.url(1) == SEARXNG["results"][0]["url"] and store.url(6) == SECOND["results"][0]["url"]
    assert store.url(0) is None and store.url(11) is None


def test_a_look_up_outside_a_turn_numbers_from_one_each_time() -> None:
    fake = serve()
    assert [r["result"] for r in results(run(make(fake), "search_web", query="first"))] == [1, 2, 3, 4, 5]
    assert [r["result"] for r in results(run(make(fake), "search_web", query="first"))] == [1, 2, 3, 4, 5]


def test_a_page_read_is_kept_for_the_turn_with_its_title_and_the_text_she_was_given() -> None:
    fake = serve({PAGE: html("<html><head><title> Hello \n there </title></head><body><p>" + "x" * (CONFIG.page_chars + 9)
                             + "</p></body></html>")})
    store = Results()
    client = fake.client()
    pages = Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), store)
    run(pages, "search_web", query="first")
    assert store.page(4) is None
    given = json.loads(run(pages, "read_page", result=4).content)["text"]
    kept = store.page(4)
    assert kept is not None and kept.title == "Hello there"
    assert kept.text.startswith(given) and len(kept.text) == len("Hello there\n") + CONFIG.page_chars + 9 > len(given)
    assert store.page(5) is None and store.page(99) is None
    run(pages, "read_page", result=99)
    assert store.page(99) is None
