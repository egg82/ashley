"""A code or document piece put up from a page she read: `Pages` reads a paste or a file view as its plain source
(`raw_source`), keeps the text for the turn, and the bench tools write it into the piece under its address by `result`,
refusing a page the kind cannot hold whole. The pastebin pages are invented responses in the shape of a public paste
(`search_captures/pastebin-*`, the html as a paste site serves it)."""

import asyncio

import httpx2
import pytest

from ashley import services
from ashley.channels.said_links import by_people
from ashley.conversations.conversations import NullConversations
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import look_up_config, page_text, raw_source
from ashley.tools.bench_tools import BenchTools
from ashley.tools.pages import Pages
from ashley.tools.results import ReadPage, Results
from ashley.tools.web_search import WebSearchTools
from ashley.workshop.commands import Add
from ashley.workshop.model import HER, Text
from ashley.workshop.workshop import Workshop
from page_support import Resolver, html
from search_support import CAPTURES, CONFIG as SEARCH, SEARXNG_URL, Fake
from test_bench_reference import Deciding, OWNER, call

CONFIG = look_up_config.load()
ID = "Zx9Qw3Lm"
PASTE = f"https://pastebin.com/{ID}"
RAW = f"https://pastebin.com/raw/{ID}"
RAW_TEXT = (CAPTURES / "pastebin-raw.txt").read_bytes().decode()
PAGE_TEXT = (CAPTURES / "pastebin-page.html").read_text(encoding="utf-8")
LINE = "            if rise - value + (limit - 1) >= 0:"


def served(config: look_up_config.LookUpConfig = CONFIG) -> tuple[Pages, Results, Fake]:
    pages = {PASTE: html(PAGE_TEXT), RAW: html(RAW_TEXT, kind="text/plain; charset=utf-8")}
    fake = Fake(lambda request: pages.get(str(request.url), httpx2.Response(404)))
    store = Results()
    client = fake.client()
    return Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, config, Resolver(), store), store, fake


def read(pages: Pages, number: int) -> ToolResult:
    return asyncio.run(pages.call(ToolCall("r", "read_page", {"result": number})))


def put_up(store: Results, kind: str = "code", **args: object) -> ToolResult:
    services.register(Workshop, Deciding())
    return call(BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5)),
                "bench_add", kind=kind, title="Script", **args)


@pytest.fixture(autouse=True)
def conversations() -> None:
    from ashley.conversations.conversations import Conversations
    services.register(Conversations, NullConversations())


def test_the_pastes_html_page_loses_its_indentation_which_is_why_the_raw_address_is_read() -> None:
    text = page_text.text_of(PAGE_TEXT)
    assert LINE.strip() in text.split("\n")
    assert LINE not in text.split("\n")


def test_reading_a_paste_fetches_its_raw_source_and_keeps_every_line_intact() -> None:
    pages, store, fake = served()
    number = store.record(PASTE)
    assert not read(pages, number).is_error
    assert [str(r.url) for r in fake.requests] == [RAW]
    kept = store.page(number)
    assert kept is not None and not kept.cut
    lines = kept.text.splitlines(keepends=True)
    assert len(lines) == 371 and lines[111] == LINE + "\r\n"


def test_a_pastes_text_is_put_up_as_a_code_piece_under_its_address() -> None:
    pages, store, _ = served()
    read(pages, store.record(PASTE))
    shop = Deciding()
    services.register(Workshop, shop)
    got = call(BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5)), "bench_add",
               kind="code", title="Script", result=1)
    assert not got.is_error, got.content
    (add,) = shop.seen
    assert isinstance(add, Add) and add.kind == "code" and add.text.title == "Script"
    lines = add.text.body.splitlines()
    assert lines[0] == f"Source: {PASTE}" and len(lines) == 372 and lines[112] == LINE and "\r" not in add.text.body


def test_a_document_piece_gets_the_address_as_its_first_paragraph() -> None:
    store = Results()
    store.record(PASTE)
    store.keep(1, ReadPage("", "alpha\nbeta"))
    shop = Deciding()
    services.register(Workshop, shop)
    got = call(BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5)), "bench_add",
               kind="document", title="Notes", result=1)
    assert not got.is_error, got.content
    assert shop.seen == [Add(HER, "document", Text("Notes", f"Source: {PASTE}\n\nalpha\nbeta"), "medium")]


def test_a_page_longer_than_the_kind_holds_is_refused_and_nothing_is_added() -> None:
    store = Results()
    store.record(PASTE)
    store.keep(1, ReadPage("", "x" * 50000))
    shop = Deciding()
    services.register(Workshop, shop)
    got = call(BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5)), "bench_add",
               kind="code", title="Script", result=1)
    assert got.is_error and got.content.startswith("page_too_long:")
    assert shop.seen == []


def test_a_page_cut_by_the_byte_limit_is_refused_not_stored_short() -> None:
    config = look_up_config.LookUpConfig(**{**CONFIG.__dict__, "page_bytes": 5000})
    pages, store, _ = served(config)
    number = store.record(PASTE)
    read(pages, number)
    kept = store.page(number)
    assert kept is not None and kept.cut
    got = put_up(store, result=number)
    assert got.is_error and got.content.startswith("page_cut:")


def test_a_result_that_was_not_read_or_does_not_exist_is_refused() -> None:
    store = Results()
    store.record(PASTE)
    assert put_up(store, result=1).content.startswith("unread_page:")
    assert put_up(store, result=9).content.startswith("unknown_result:")


def test_a_page_is_put_up_by_result_alone() -> None:
    store = Results()
    store.record(PASTE)
    store.keep(1, ReadPage("", "alpha"))
    assert put_up(store, result=1, body="mine").content.startswith("bad_arguments:")
    assert put_up(store, result=1, start=3).content.startswith("bad_arguments:")


@pytest.mark.parametrize(("url", "raw"), [
    (PASTE, RAW),
    ("https://github.com/egg82/fetcharr/blob/main/docs/a%20b.md?plain=1#L3",
     "https://raw.githubusercontent.com/egg82/fetcharr/main/docs/a%20b.md"),
    ("https://github.com/egg82/fetcharr/blob/v1.2/src/x.py", "https://raw.githubusercontent.com/egg82/fetcharr/v1.2/src/x.py"),
    (f"https://pastebin.com/raw/{ID}", None),
    ("https://pastebin.com/u/someone", None),
    ("https://pastebin.com/abc", None),
    ("http://pastebin.com/Zx9Qw3Lm", None),
    ("https://pastebin.com.example.org/Zx9Qw3Lm", None),
    ("https://notpastebin.com/Zx9Qw3Lm", None),
    ("https://pastebin.com@example.org/Zx9Qw3Lm", None),
    ("https://pastebin.com:8443/Zx9Qw3Lm", None),
    ("https://github.com/egg82/fetcharr", None),
    ("https://github.com/egg82/fetcharr/tree/main/docs", None),
    ("https://example.org/egg82/fetcharr/blob/main/x.py", None),
])
def test_only_a_paste_and_a_github_file_view_have_a_raw_address(url: str, raw: str | None) -> None:
    assert raw_source.raw_url(url) == raw
