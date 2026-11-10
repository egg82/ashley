"""`bench_read_piece` on a site or video piece also gives the page it shows, read from the address the piece stores: a
YouTube video's details (the captured watch page), its description's links numbered into the turn's `Results`, which
then put up a code piece from a paste. The page read is itself numbered and kept, so a recipe piece goes up from a
link card by that number (a captured recipe page's JSON-LD) without a second search. A page that cannot be read says
so, and gives no number."""

import asyncio
import dataclasses
import json

import httpx2
import pytest

from ashley import services
from ashley.channels.said_links import by_people
from ashley.conversations.conversations import NullConversations, Conversations
from ashley.inference.model import ToolCall
from ashley.tools import look_up_config, recipe_ld
from ashley.tools.bench_tools import BenchTools
from ashley.tools.page_reader import FetchedPageReader, PageReader
from ashley.tools.pages import Pages
from ashley.tools.results import Results
from ashley.tools.web_search import WebSearchTools
from ashley.workshop import recipe
from ashley.workshop.commands import Add
from ashley.workshop.workshop import Workshop
from page_support import Resolver, html
from recipe_support import CRANBERRY, page_of
from search_support import CAPTURES, CONFIG as SEARCH, SEARXNG_URL, Fake
from test_bench_reference import Deciding, OWNER, call, piece
from youtube_read_support import PLAYER, VIDEO, WATCH, WATCH_HTML

LINKED = "https://www.youtube.com/watch?v=Qw3rTy7UiOp&t=531s"
PASTE = "https://pastebin.com/Zx9Qw3Lm"
RAW = "https://pastebin.com/raw/Zx9Qw3Lm"
RAW_TEXT = (CAPTURES / "pastebin-raw.txt").read_bytes().decode()
LINE = "            if rise - value + (limit - 1) >= 0:"
CONFIG = look_up_config.load()


def serve(pages: dict[str, httpx2.Response]) -> Fake:
    fake = Fake(lambda request: pages.get(str(request.url), httpx2.Response(404)))
    services.register(PageReader, FetchedPageReader(fake.client(), Resolver()))
    return fake


@pytest.fixture(autouse=True)
def wired() -> None:
    services.register(Conversations, NullConversations())


def read_piece(shop: Deciding, store: Results, pid: int) -> dict[str, object]:
    services.register(Workshop, shop)
    got = call(BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5)),
               "bench_read_piece", piece_id=pid)
    assert not got.is_error, got.content
    body: dict[str, object] = json.loads(got.content)
    return body


def test_a_video_pieces_read_gives_the_videos_details_and_numbers_its_links() -> None:
    fake = serve({WATCH: html(WATCH_HTML)})
    shop = Deciding(pieces=(piece(2, "video", json.dumps({"url": f"https://youtu.be/{VIDEO}?si=x"})),))
    store = Results()
    got = read_piece(shop, store, 2)
    text = str(got["page_text"])
    assert text.startswith("Title: " + PLAYER["videoDetails"]["title"] + "\nChannel: Loaf Lab\n")
    assert f"{LINKED} (result 1)" in text and store.url(1) == LINKED
    assert json.loads(str(got["body"])) == {"url": f"https://youtu.be/{VIDEO}?si=x"}
    assert [str(r.url) for r in fake.requests] == [WATCH]


def test_a_link_of_the_description_puts_a_paste_up_as_a_code_piece() -> None:
    page = WATCH_HTML.replace("Music: Morning Rise", f"Code {PASTE} Music: Morning Rise")
    fake = serve({WATCH: html(page), PASTE: html("<p>js</p>"), RAW: html(RAW_TEXT, kind="text/plain; charset=utf-8")})
    shop = Deciding(pieces=(piece(2, "video", json.dumps({"url": WATCH})),))
    store = Results()
    text = str(read_piece(shop, store, 2)["page_text"])
    number = next(n for n in range(1, 5) if store.url(n) == PASTE)
    assert f"{PASTE} (result {number})" in text
    client = fake.client()
    pages = Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, CONFIG, Resolver(), store)
    assert not asyncio.run(pages.call(ToolCall("r", "read_page", {"result": number}))).is_error
    got = call(BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5)), "bench_add",
               kind="code", title="Script", result=number)
    assert not got.is_error, got.content
    (add,) = [c for c in shop.seen if isinstance(c, Add)]
    assert add.kind == "code" and LINE in add.text.body.splitlines()


def test_a_site_pieces_read_gives_its_pages_text() -> None:
    serve({"https://example.org/hours": html("<p>open nine to five</p>")})
    got = read_piece(Deciding(pieces=(piece(3, "site", "https://example.org/hours"),)), Results(), 3)
    assert got["page_text"] == "open nine to five"


def test_a_link_card_read_earlier_goes_up_as_a_recipe_piece_by_the_number_its_read_gives() -> None:
    address = "https://recipes.example/cranberry-relish"
    serve({address: html(page_of(CRANBERRY))})
    shop = Deciding(pieces=(piece(3, "site", address),))
    store = Results()
    store.record("https://example.org/searched-earlier")
    got = read_piece(shop, store, 3)
    assert got["result"] == 2 and store.url(2) == address
    tools = BenchTools(OWNER.household_id, OWNER.person_id, 4, results=store, said=by_people(5))
    added = call(tools, "bench_add", kind="recipe", title="Cranberry sauce", result=2, serves=6)
    assert not added.is_error, added.content
    (add,) = [c for c in shop.seen if isinstance(c, Add)]
    published = recipe_ld.recipe_in(page_of(CRANBERRY), address)
    assert published is not None and recipe.recipe_of(add.text.body) == dataclasses.replace(published, serves=6)


def test_a_page_that_cannot_be_read_is_unavailable_not_empty() -> None:
    serve({})
    store = Results()
    got = read_piece(Deciding(pieces=(piece(3, "site", "https://example.org/gone"),)), store, 3)
    assert got["page_unavailable"] is True and "page_text" not in got
    assert "result" not in got and store.next_number() == 1


def test_other_pieces_and_video_files_have_no_page() -> None:
    serve({})
    shop = Deciding(pieces=(piece(1, "note", "https://example.org/x"),
                            piece(2, "video", json.dumps({"url": "https://example.org/a.mp4"}))))
    for pid in (1, 2):
        got = read_piece(shop, Results(), pid)
        assert "page_text" not in got and "page_unavailable" not in got


def test_a_private_address_is_refused_not_fetched() -> None:
    fake = serve({"https://internal.example/x": html("secret")})
    services.register(PageReader, FetchedPageReader(fake.client(), Resolver({"internal.example": ["10.0.0.5"]})))
    got = read_piece(Deciding(pieces=(piece(3, "site", "https://internal.example/x"),)), Results(), 3)
    assert got["page_unavailable"] is True and fake.requests == []
