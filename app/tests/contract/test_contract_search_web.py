"""`WebSearchTools`: one tool `search_web` over SearXNG. The request, the result shape (cut and capped from a
captured SearXNG body), every failure's exact reason and outcome, and a log line that never carries the query, a URL
or a title."""

import copy
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from ashley import logs
from ashley.tools.web_search import WebSearchTools
from conversations_support import events
from search_contract_support import (BROKEN_BODIES, CONFIG, MARK, SEARXNG_URL, SEARXNG, Web, call, cfg, connect_web, json_web, run,
                            timeout_web)

NEEDS_QUERY = "search_web needs a query"
DID_NOT_ANSWER = "web search did not answer"


def body(**changes: Any) -> dict[str, Any]:
    return {**copy.deepcopy(SEARXNG), **changes}


def search(web: Web, arguments: dict[str, object], config: Any = CONFIG, base_url: str = SEARXNG_URL) -> Any:
    return run(WebSearchTools(web.client(), config, base_url).call(call("search_web", arguments)))


def parsed(web: Web, arguments: dict[str, object] | None = None, config: Any = CONFIG) -> dict[str, Any]:
    result = search(web, arguments or {"query": "when does daylight saving time end"}, config)
    assert not result.is_error, result.content
    return json.loads(result.content)


def test_the_captured_body_has_the_shape_these_tests_rely_on() -> None:
    results = SEARXNG["results"]
    assert len(results) == 8 and SEARXNG["answers"] == []
    assert [r["publishedDate"] for r in results].count(None) == 7 and results[2]["publishedDate"]
    assert any(len(r["content"]) > 100 for r in results)


def test_the_catalogue_is_one_tool_with_a_query_parameter() -> None:
    c = run(WebSearchTools(Web().client(), CONFIG, SEARXNG_URL).catalogue())
    (tool,) = c.specs
    assert tool.name == "search_web"
    assert tool.parameters == {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    assert "web" in tool.description.lower() and "instruction" in tool.description.lower()
    assert c.instructions is None
    assert c.unreachable == ()


def test_the_request_is_a_get_of_search_with_q_format_json_and_the_configured_timeout() -> None:
    web = json_web(SEARXNG)
    search(web, {"query": "when does daylight saving time end"})
    (request,) = web.requests
    assert request.method == "GET"
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == "https://searx.test/search"
    assert parse_qs(request.url.query.decode()) == {"q": ["when does daylight saving time end"], "format": ["json"]}
    assert request.extensions["timeout"]["read"] == CONFIG.timeout_s


def test_a_result_has_title_snippet_and_the_host_as_source_in_searxngs_order() -> None:
    out = parsed(json_web(SEARXNG))
    assert [r["title"] for r in out["results"]] == [r["title"] for r in SEARXNG["results"][:5]]
    first = out["results"][0]
    assert first["source"] == "www.timeanddate.com"
    assert first["snippet"] == SEARXNG["results"][0]["content"]
    assert set(first) == {"result", "title", "snippet", "source"}
    assert [r["source"] for r in out["results"]][1] == "abcnews.com"


def test_published_appears_only_when_searxng_gave_a_date() -> None:
    out = parsed(json_web(SEARXNG))
    assert "2026-10-27" in out["results"][2]["published"]
    assert [("published" in r) for r in out["results"]] == [False, False, True, False, False]


@pytest.mark.parametrize(("cap", "count"), [(1, 1), (3, 3), (5, 5), (8, 8), (50, 8)])
def test_at_most_web_results_come_back(cap: int, count: int) -> None:
    out = parsed(json_web(SEARXNG), config=cfg(web_results=cap))
    assert [r["title"] for r in out["results"]] == [r["title"] for r in SEARXNG["results"][:count]]


def test_a_snippet_is_cut_to_snippet_chars_and_a_short_one_is_whole() -> None:
    out = parsed(json_web(SEARXNG), config=cfg(snippet_chars=100, web_results=8))
    for got, real in zip(out["results"], SEARXNG["results"], strict=True):
        assert len(got["snippet"]) <= 100
        assert real["content"].startswith(got["snippet"].rstrip())
        if len(real["content"]) > 100:
            assert len(got["snippet"].rstrip()) >= 90, "cut near the limit, not to a stub"
    assert out["results"][0]["snippet"] != SEARXNG["results"][0]["content"]


def test_a_snippet_under_the_limit_is_not_changed() -> None:
    out = parsed(json_web(SEARXNG), config=cfg(snippet_chars=1000))
    assert [r["snippet"] for r in out["results"]] == [r["content"] for r in SEARXNG["results"][:5]]


def test_answers_appear_only_when_searxng_gave_some() -> None:
    assert "answers" not in parsed(json_web(SEARXNG))
    out = parsed(json_web(body(answers=["November 1, 2026", "Nov 1"])))
    assert out["answers"] == ["November 1, 2026", "Nov 1"]


def test_no_results_is_ok_and_empty(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    out = parsed(json_web(body(results=[])))
    assert out["results"] == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["outcome"], line["results"]) == ("ok", "0")


@pytest.mark.parametrize("arguments", [{}, {"query": ""}, {"query": "   \n"}, {"query": 7}, {"query": None},
                                       {"query": ["a"]}, {"q": "right idea wrong key"}])
def test_a_missing_blank_or_non_string_query_is_an_error_and_asks_nothing(arguments: dict[str, object],
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    web = json_web(SEARXNG)
    logs.setup()
    capsys.readouterr()
    result = search(web, arguments)
    assert result.is_error and result.content == NEEDS_QUERY and result.call_id == "c1"
    assert web.requests == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("search_web", "error")


@pytest.mark.parametrize("make", [timeout_web, connect_web, *[
    (lambda k=k: Web(BROKEN_BODIES[k])) for k in BROKEN_BODIES]])
def test_every_failure_to_answer_is_unavailable_with_one_reason(make: Any, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    result = search(make(), {"query": f"how {MARK} works"})
    assert result.is_error and result.content == DID_NOT_ANSWER
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("search_web", "unavailable")


def test_a_name_other_than_search_web_is_unknown_and_asks_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    web = json_web(SEARXNG)
    logs.setup()
    capsys.readouterr()
    result = run(WebSearchTools(web.client(), CONFIG, SEARXNG_URL).call(call("find_places", {"query": MARK})))
    assert result.is_error and MARK not in result.content and web.requests == []
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("find_places", "unknown_tool")


def test_an_ok_call_logs_name_outcome_result_count_and_duration(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    parsed(json_web(SEARXNG))
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"], line["results"]) == ("search_web", "ok", "5")
    assert line["duration_ms"].isdigit()


def test_the_query_urls_titles_and_snippets_reach_no_log_line_and_no_error(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    reasons: list[str] = []
    for web in (json_web(SEARXNG), json_web(body(results=[])), timeout_web(), connect_web(),
                *[Web(r) for r in BROKEN_BODIES.values()]):
        reasons.append(search(web, {"query": f"{MARK} secret plans"}).content)
    reasons.append(search(json_web(SEARXNG), {"query": "  "}).content)
    out = capsys.readouterr().out
    assert len(events(out, "tools.call")) == len(reasons) == 12, "control: every call was logged"
    for leaked in (MARK, "secret plans", "searx.test", "https://", "timeanddate", "daylight", SEARXNG["results"][0]["title"],
                   SEARXNG["results"][0]["content"][:30]):
        assert leaked not in out
    assert all(MARK not in r and "searx.test" not in r for r in reasons[2:])


def test_the_call_id_is_the_asked_one() -> None:
    result = run(WebSearchTools(json_web(SEARXNG).client(), CONFIG, SEARXNG_URL).call(call("search_web", {"query": "x"}, "id-42")))
    assert result.call_id == "id-42" and not result.is_error


def test_a_result_from_a_url_without_a_host_does_not_break_the_call() -> None:
    odd = body()
    odd["results"][0]["url"] = "not a url"
    result = search(json_web(odd), {"query": "x"})
    assert not result.is_error and len(json.loads(result.content)["results"]) == 5


def test_an_http_error_status_is_unavailable_even_with_a_valid_body() -> None:
    assert search(json_web(SEARXNG, status=503), {"query": "x"}).content == DID_NOT_ANSWER


def test_the_request_url_is_built_from_the_configured_base() -> None:
    web = json_web(SEARXNG)
    search(web, {"query": "x"}, base_url="https://elsewhere.test:8443")
    assert urlparse(str(web.requests[0].url)).netloc == "elsewhere.test:8443"
    assert isinstance(web.requests[0], httpx2.Request)
