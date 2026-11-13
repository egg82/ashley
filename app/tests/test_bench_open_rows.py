"""What is still open on a bench reaches every later turn: the moment layer lists each guessed row of the bench's
measurements pieces, shown or not, however far into its piece, and none from a piece written after outside words or of
an outside kind; a bench with none says nothing extra. And a page `read_page` reads that publishes a recipe gives the
recipe first."""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace

import httpx2

from ashley.tools import look_up_config
from ashley.tools.bench_now import OPEN_HEAD, OUTSIDE_HEAD, now, open_rows
from ashley.tools.pages import Pages
from ashley.tools.results import Results
from ashley.tools.web_search import WebSearchTools
from ashley.inference.model import ToolCall
from ashley.workshop.commands import ShownRow
from ashley.workshop.model import Bench, Piece, Place, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import BenchView
from bench_tools_support import EPOCH
from page_support import Resolver, html
from recipe_support import MASH, page_of
from search_support import CONFIG as SEARCH, SEARXNG_URL, Fake, captured

RULES = Rules({"note": Kind("note", "stored", "Note", 4000),
               "measurements": Kind("measurements", "stored", "Measurements", 50000, "measurements")},
              max_pieces=10, title_max_chars=40, recent_commands=5, undo_window=100)


def rows(*items: Mapping[str, object]) -> str:
    return json.dumps({"items": list(items)})


def view(*pieces: Piece) -> BenchView:
    return BenchView(Bench(9, 10, 1, "Dinner", EPOCH, None), pieces, ())


def piece(pid: int, kind: str, body: str, outside: bool = False) -> Piece:
    return Piece(pid, kind, Text("t", body), 1, Place(pid, "medium"), pid, outside)


HEADCOUNT = {"name": "headcount", "value": 6, "unit": "count", "source": "measured"}
TURKEY = {"name": "turkey_breast", "value": 2500, "unit": "g", "source": "guessed"}
PIES = {"name": "pies", "value": 1, "unit": "count", "source": "guessed"}


def test_every_guessed_row_is_listed_with_whether_it_was_shown() -> None:
    padded = rows(HEADCOUNT, *({"name": f"r{i}", "value": i, "unit": "g", "source": "datasheet"} for i in range(50)),
                  TURKEY, PIES)
    shown = replace(view(piece(1, "note", "plan"), piece(2, "measurements", padded)),
                    surfaced=frozenset({(2, ShownRow("turkey_breast", "2500 g"))}))
    assert open_rows(shown, RULES) == [
        {"piece": 2, "name": "turkey_breast", "value": 2500, "unit": "g", "shown": True},
        {"piece": 2, "name": "pies", "value": 1, "unit": "count", "shown": False}]
    text = now(shown, RULES, 40)
    assert OPEN_HEAD in text and text.rstrip().endswith('"shown": false}')


def test_rows_written_after_outside_words_are_not_listed_and_none_says_nothing() -> None:
    tainted = view(piece(2, "measurements", rows(TURKEY), outside=True))
    assert open_rows(tainted, RULES) == [] and OPEN_HEAD not in now(tainted, RULES, 40)
    settled = view(piece(2, "measurements", rows(HEADCOUNT)))
    assert OPEN_HEAD not in now(settled, RULES, 40)


def test_a_piece_written_after_outside_words_gets_an_ids_only_line_with_its_count_of_unconfirmed_rows() -> None:
    form = {"kind": "choice", "name": "turkey_brand", "label": "Turkey Marker XYZ", "value": "Kirkland", "source": "guessed"}
    tainted = view(piece(1, "measurements", rows(HEADCOUNT)), piece(2, "measurements", rows(HEADCOUNT, TURKEY, PIES, form),
                                                                    outside=True),
                   piece(3, "measurements", rows(HEADCOUNT), outside=True))
    text = now(tainted, RULES, 40)
    assert text.endswith(f'{OUTSIDE_HEAD}\n{{"piece": 2, "unconfirmed": 3}}')
    assert "Kirkland" not in text and "Turkey Marker XYZ" not in text and "turkey_breast" not in text
    assert OUTSIDE_HEAD not in now(view(piece(2, "measurements", rows(TURKEY))), RULES, 40)


def test_a_read_page_with_a_recipe_gives_the_recipe_first() -> None:
    searx = captured("searxng")
    url = searx["results"][0]["url"]

    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "search.test":
            return httpx2.Response(200, json=searx)
        return html(page_of(MASH)) if str(request.url) == url else httpx2.Response(404)

    client = Fake(answer).client()
    numbered = Results()
    pages = Pages(WebSearchTools(client, SEARCH, SEARXNG_URL), client, look_up_config.load(), Resolver(), numbered)
    asyncio.run(pages.call(ToolCall("s", "search_web", {"query": "mash"})))
    got = json.loads(asyncio.run(pages.call(ToolCall("r", "read_page", {"result": 1}))).content)
    assert list(got) == ["result", "recipe", "text"]
    assert got["recipe"].startswith("Garlic Yukon Gold Mashed Potatoes\nSource: " + url)
    kept = numbered.page(1)
    assert kept is not None and kept.recipe is not None and kept.recipe.url == url
