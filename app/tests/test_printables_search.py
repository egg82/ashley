"""`search_printables`, a look-up source: what it shows (numbered, no file ids, no links), that the numbers continue the
turn's and mean the model's page, how it fails, and what it logs."""

import asyncio
import json

import pytest

from ashley import logs, services
from ashley.printables.printables import NullPrintables, Printables
from ashley.tools import look_up_config, results
from ashley.wiring import look_up_sources
from ashley.tools.printables_search import PrintablesSearchTools
from ashley.tools.web_search import WebSearchTools
from printables_support import CONFIG, adapter, api, recorded
from search_support import CONFIG as SEARCH, SEARXNG_URL
from search_support import call, events, serving


def search(numbered: results.Results, **arguments: object) -> tuple[dict[str, list[dict[str, object]]], bool]:
    tools = PrintablesSearchTools(adapter(api(recorded())), CONFIG, numbered)
    got = asyncio.run(tools.call(call("search_printables", **arguments)))
    return (json.loads(got.content) if not got.is_error else {}), got.is_error


def test_the_catalogue_is_one_search_tool_taking_a_query() -> None:
    catalogue = asyncio.run(PrintablesSearchTools(NullPrintables(), CONFIG, results.Results()).catalogue())
    (spec,) = catalogue.specs
    assert spec.name == "search_printables" and spec.parameters["required"] == ["query"]


def test_she_is_shown_each_model_numbered_with_its_counts_summary_and_file_names() -> None:
    numbered = results.Results()
    numbered.record("https://example.org/earlier")
    shown, failed = search(numbered, query="pencil cup")
    assert not failed
    first = shown["results"][0]
    assert first == {
        "result": 2, "title": "DESK PENCIL CUP", "likes": 45, "downloads": 683, "makes": 7, "rating": 5.0,
        "snippet": "I liked the pencil cup design but also needed a place for my sticky notes so I "
                   "modified it to add a note…",
        "files": ["cup_v3.stl"]}
    assert [r["result"] for r in shown["results"]] == [2, 3, 4, 5, 6]
    assert [r["files"] for r in shown["results"]][1] == [
        "Cup_Note_Holder_2Notes.3mf", "Cup_Note_Holder_2Notes.stl", "Cup_Note_Holder_Single.stl",
        "Cup_Note_Holder_Single.3mf"]


def test_a_number_means_the_models_page_and_the_text_shows_no_link_and_no_file_id() -> None:
    numbered = results.Results()
    shown, _ = search(numbered, query="pencil cup")
    assert numbered.url(1) == "https://www.printables.com/model/100001-desk-pencil-cup"
    assert numbered.url(5) == "https://www.printables.com/model/100005-pencil-cupstand-3-and-4-slots"
    text = json.dumps(shown)
    assert "http" not in text and "200001" not in text and "printables.com" not in text


@pytest.mark.parametrize("arguments", [{}, {"query": "  "}, {"query": 3}])
def test_a_missing_query_is_an_error_and_numbers_nothing(arguments: dict[str, object]) -> None:
    numbered = results.Results()
    _, failed = search(numbered, **arguments)
    assert failed and numbered.next_number() == 1


def test_printables_not_answering_is_unavailable_and_numbers_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    numbered = results.Results()
    got = asyncio.run(PrintablesSearchTools(NullPrintables(), CONFIG, numbered).call(call("search_printables", query="x")))
    assert got.is_error and got.content == "Printables did not answer" and numbered.next_number() == 1
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert (line["tool"], line["outcome"]) == ("search_printables", "unavailable")


def test_another_name_is_unknown() -> None:
    got = asyncio.run(PrintablesSearchTools(NullPrintables(), CONFIG, results.Results()).call(call("search_web", query="x")))
    assert got.is_error and "no tool named" in got.content


def test_the_look_up_offers_printables_beside_the_web_and_numbers_both_in_one_store() -> None:
    client = serving({"results": [{"url": "https://example.org/a", "title": "A"}]}).client()
    numbered = results.Results()
    services.register(Printables, adapter(api(recorded())))
    try:
        with results.bound(numbered):
            sources = look_up_sources(WebSearchTools(client, SEARCH, SEARXNG_URL), None, CONFIG, client,
                                      look_up_config.load())
            names = [s.name for s in asyncio.run(sources.catalogue()).specs]
            asyncio.run(sources.call(call("search_web", query="x")))
            asyncio.run(sources.call(call("search_printables", query="pencil cup")))
    finally:
        services.unregister(Printables)
    assert names == ["search_web", "read_page", "search_printables"]
    assert numbered.url(1) == "https://example.org/a" and numbered.url(2) == (
        "https://www.printables.com/model/100001-desk-pencil-cup")


def test_with_no_search_address_the_look_up_offers_no_web() -> None:
    client = serving({}).client()
    sources = look_up_sources(None, None, CONFIG, client, look_up_config.load())
    assert [s.name for s in asyncio.run(sources.catalogue()).specs] == ["search_printables"]
