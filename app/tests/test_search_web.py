"""`WebSearchTools` against a captured SearXNG answer: what it asks, what she is shown, how it fails, what it logs."""

import asyncio
import json
from dataclasses import replace

import httpx2
import pytest

from ashley import logs
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.search_config import SearchConfig
from ashley.tools.web_search import WebSearchTools
from search_support import CONFIG, SEARXNG_URL, Fake, call, captured, events, raising, serving

QUERY = "when does daylight saving time end"


def search(fake: Fake, config: SearchConfig = CONFIG, **arguments: object) -> ToolResult:
    return asyncio.run(WebSearchTools(fake.client(), config, SEARXNG_URL).call(call("search_web", **arguments)))


def test_the_catalogue_is_one_search_tool() -> None:
    catalogue = asyncio.run(WebSearchTools(serving({}).client(), CONFIG, SEARXNG_URL).catalogue())
    (spec,) = catalogue.specs
    assert spec.name == "search_web"
    assert dict(spec.parameters) == {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    assert catalogue.instructions is None and catalogue.unreachable == ()


def test_it_asks_searxng_for_json() -> None:
    fake = serving(captured("searxng"))
    search(fake, query=QUERY)
    (request,) = fake.requests
    assert str(request.url).startswith("https://search.test/search?")
    assert dict(request.url.params) == {"q": QUERY, "format": "json"}
    assert request.extensions["timeout"]["read"] == CONFIG.timeout_s


def test_she_is_shown_the_first_results_snippets_and_sites() -> None:
    body = captured("searxng")
    result = search(serving(body), query=QUERY)
    assert not result.is_error and result.call_id == "c1"
    shown = json.loads(result.content)
    assert "answers" not in shown
    assert len(shown["results"]) == CONFIG.web_results
    first, raw = shown["results"][0], body["results"][0]
    assert first == {"result": 1, "title": raw["title"], "snippet": raw["content"][:CONFIG.snippet_chars],
                     "source": "www.timeanddate.com"}
    assert [r["result"] for r in shown["results"]] == list(range(1, CONFIG.web_results + 1))
    assert [r["source"] for r in shown["results"]][1] == "abcnews.com"


def test_snippets_are_cut_and_answers_and_dates_carried() -> None:
    body = captured("searxng")
    body["answers"] = ["Sunday 1 November", {"answer": "2 am", "url": "https://x.test/"}, {"other": 1}]
    body["results"][0]["publishedDate"] = "2026-10-01T00:00:00"
    shown = json.loads(search(serving(body), replace(CONFIG, snippet_chars=10, web_results=2), query=QUERY).content)
    assert [len(r["snippet"]) for r in shown["results"]] == [10, 10]
    assert shown["results"][0]["published"] == "2026-10-01T00:00:00"
    assert "published" not in shown["results"][1]
    assert shown["answers"] == ["Sunday 1 November", "2 am"]


def test_no_results_is_an_empty_list() -> None:
    result = search(serving({"results": [], "answers": []}), query=QUERY)
    assert not result.is_error and json.loads(result.content) == {"results": []}


@pytest.mark.parametrize("arguments", [{}, {"query": 3}, {"query": "  "}])
def test_a_missing_query_is_an_error_and_asks_nothing(arguments: dict[str, object]) -> None:
    fake = serving(captured("searxng"))
    result = asyncio.run(WebSearchTools(fake.client(), CONFIG, SEARXNG_URL).call(ToolCall("c1", "search_web", arguments)))
    assert result.is_error and result.content == "search_web needs a query"
    assert fake.requests == []


@pytest.mark.parametrize("fake", [
    raising(httpx2.ReadTimeout("slow")), raising(httpx2.ConnectError("refused")), serving({"error": "x"}, 500),
    serving({"no": "results"}), Fake(lambda _: httpx2.Response(200, text="<html>")),
])
def test_a_source_that_does_not_answer_is_unavailable(fake: Fake) -> None:
    result = search(fake, query=QUERY)
    assert result.is_error and result.content == "web search did not answer"


def test_another_name_is_unknown() -> None:
    result = asyncio.run(WebSearchTools(serving({}).client(), CONFIG, SEARXNG_URL).call(call("find_places", query="x")))
    assert result.is_error and result.content == "no tool named find_places"


def test_the_log_carries_outcome_and_count_never_the_query(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    search(serving(captured("searxng")), query="PLANTED-QUERY-zq")
    search(raising(httpx2.ConnectError("refused")), query="PLANTED-QUERY-zq")
    out = capsys.readouterr().out
    lines = events(out, "tools.call")
    assert [(e["tool"], e["outcome"], e["results"]) for e in lines] == [
        ("search_web", "ok", str(CONFIG.web_results)), ("search_web", "unavailable", "0")]
    assert all("duration_ms" in e for e in lines)
    assert "PLANTED-QUERY-zq" not in out and "timeanddate" not in out
