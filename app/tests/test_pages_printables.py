"""`read_page` on a Printables model's page reads the model through the API, never the site: its details, its files by
name and size with no id, and the description as text. A look-alike address is read as any page."""

import asyncio
import json

from ashley import services
from ashley.inference.model import ToolCall
from ashley.printables.printables import Printables
from ashley.tools import look_up_config
from ashley.tools.pages import Pages
from ashley.tools.results import Results
from ashley.tools.web_search import WebSearchTools
from page_support import Resolver, site
from printables_support import adapter, api, recorded
from search_support import CONFIG as SEARCH, SEARXNG_URL

CONFIG = look_up_config.load()
MODEL = "https://www.printables.com/model/100002-desk-pencil-cup"


def read(address: str) -> tuple[dict[str, object], list[str], bool]:
    fake = api(recorded())
    services.register(Printables, adapter(fake))
    try:
        client = site({}).client()
        numbered = Results()
        numbered.record(address)
        got = asyncio.run(Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), numbered)
                          .call(ToolCall("p1", "read_page", {"result": 1})))
    finally:
        services.unregister(Printables)
    return (json.loads(got.content) if not got.is_error else {}), [str(r.url) for r in fake.requests], got.is_error


def test_a_model_page_reads_as_its_details_files_and_description() -> None:
    body, asked, failed = read(MODEL)
    assert not failed and asked == ["https://api.printables.com/graphql/"]
    text = str(body["text"])
    assert text.startswith("Title: Pencil Cup & Note Holder\nAuthor: MakerTwo\nCategory: Office\nLicense: Creative Commons")
    assert "25 likes, 623 downloads, 3 makes, rated 4.7 of 5" in text
    assert "- Cup_Note_Holder_Single.3mf (127567 bytes)" in text and "200011" not in text
    assert "remixed model of a pencil cup and note holder" in text and "<p>" not in text


def test_a_model_page_is_kept_as_the_page_read_for_its_result() -> None:
    fake = api(recorded())
    services.register(Printables, adapter(fake))
    try:
        client = site({}).client()
        numbered = Results()
        numbered.record(MODEL)
        asyncio.run(Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), numbered)
                    .call(ToolCall("p1", "read_page", {"result": 1})))
    finally:
        services.unregister(Printables)
    kept = numbered.page(1)
    assert kept is not None and kept.title == "Pencil Cup & Note Holder" and not kept.cut


def test_a_model_that_is_gone_is_a_page_that_did_not_answer() -> None:
    _, asked, failed = read("https://www.printables.com/model/1-gone")
    assert failed and asked == ["https://api.printables.com/graphql/"]


def test_a_look_alike_address_is_fetched_as_any_page() -> None:
    _, asked, failed = read("https://www.printables.com.evil.example/model/100002-x")
    assert failed and asked == []
