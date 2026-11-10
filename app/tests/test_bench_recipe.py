"""A recipe piece she puts up names a page `read_page` read this turn and how many people it is for: the server writes
the body from the recipe that page published, scales it in code, refuses a page with none and a body she typed, and an
edit may change the headcount alone. Her read of the piece is the scaled recipe as text."""

import asyncio
import dataclasses
import json
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import recipe_ld
from ashley.tools.bench_tools import BenchTools
from ashley.tools.results import ReadPage, Results
from ashley.workshop import recipe
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command, Edit
from ashley.workshop.decide import Accepted, BenchState, decide
from ashley.workshop.model import Owner, Piece, Place, Text
from ashley.workshop.workshop import Applied, Workshop
from bench_tools_support import FakeWorkshop
from recipe_support import MASH, page_of

OWNER = Owner(10, 1)
URL = "https://recipes.example/recipes/mash"
PLAIN = "https://example.org/an-article"
MASHED = recipe_ld.recipe_in(page_of(MASH), "https://elsewhere.example/x")


@dataclass
class Deciding(FakeWorkshop):
    """A Workshop whose `apply` is the real `decide` over `pieces`, keeping what it accepts."""

    seen: list[Command] = field(default_factory=list[Command])

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        decision = decide(BenchState(self.pieces, next_seq=10), command, workshop_rules.load())
        if not isinstance(decision, Accepted):
            return Applied(decision.seq, decision.reason, None)
        self.seen.append(command)
        return Applied(decision.seq, "accepted", decision.seq)


@pytest.fixture
def shop() -> Deciding:
    fake = Deciding()
    services.register(Workshop, fake)
    return fake


def numbered() -> Results:
    store = Results()
    store.record(URL)
    store.record(PLAIN)
    store.record("https://example.org/unread")
    store.keep(1, ReadPage("Mash", "Mash\nJump to recipe", recipe=MASHED))
    store.keep(2, ReadPage("Article", "Some text"))
    return store


def call(t: BenchTools, name: str, **args: object) -> ToolResult:
    return asyncio.run(t.call(ToolCall("c1", name, args)))


def tools() -> BenchTools:
    return BenchTools(OWNER.household_id, OWNER.person_id, 4, results=numbered())


def test_a_read_recipe_page_is_put_up_scaled_for_the_headcount(shop: Deciding) -> None:
    got = call(tools(), "bench_add", kind="recipe", title="Mash", result=1, serves=6)
    assert not got.is_error, got.content
    (added,) = shop.seen
    assert isinstance(added, Add) and added.kind == "recipe"
    held = recipe.recipe_of(added.text.body)
    assert held is not None and MASHED is not None
    assert held == dataclasses.replace(MASHED, url=URL, serves=6)
    assert recipe.scaled(held).factor == 1.5


@pytest.mark.parametrize(("args", "start"), [
    ({"result": 3, "serves": 6}, "unread_page:"),
    ({"result": 9, "serves": 6}, "unknown_result:"),
    ({"result": 2, "serves": 6}, "no_recipe:"),
    ({"body": "{}", "serves": 6}, "bad_arguments:"),
    ({"result": 1, "body": "typed"}, "bad_arguments:"),
    ({"result": 1, "serves": 0}, "bad_arguments:"),
    ({"result": 1, "serves": "6"}, "bad_arguments:"),
    ({"result": 1, "start": 3}, "bad_arguments:"),
])
def test_a_recipe_not_from_a_read_recipe_page_is_refused(shop: Deciding, args: dict[str, object], start: str) -> None:
    got = call(tools(), "bench_add", kind="recipe", title="Mash", **args)
    assert got.is_error and got.content.startswith(start), got.content
    assert shop.seen == []


def test_serves_is_for_a_recipe_piece_only(shop: Deciding) -> None:
    got = call(tools(), "bench_add", kind="note", title="n", body="b", serves=6)
    assert got.is_error and got.content.startswith("bad_arguments:")


def test_an_edit_changes_the_headcount_alone_and_her_read_is_the_scaled_text(shop: Deciding) -> None:
    assert MASHED is not None
    body = recipe.body_of(dataclasses.replace(MASHED, url=URL, serves=4))
    shop.pieces = (Piece(1, "recipe", Text("Mash", body), 1, Place(0, "medium"), 1),)
    hers = tools()
    shown = json.loads(call(hers, "bench_read_piece", piece_id=1).content)
    assert shown["body"].startswith("Garlic Yukon Gold Mashed Potatoes\nSource: " + URL)
    assert "- 2 lb Yukon gold potatoes" in shown["body"]
    got = call(hers, "bench_edit", piece_id=1, base_version=1, title="Mash", serves=8)
    assert not got.is_error, got.content
    (edited,) = shop.seen
    assert isinstance(edited, Edit)
    held = recipe.recipe_of(edited.text.body)
    assert held is not None and held.serves == 8 and held.ingredients == MASHED.ingredients
    typed = call(hers, "bench_edit", piece_id=1, base_version=1, title="Mash", body=body)
    assert typed.is_error and typed.content.startswith("bad_arguments:")


def test_a_recipe_piece_is_an_outside_kind() -> None:
    kind = workshop_rules.load().kinds["recipe"]
    assert (kind.format, kind.family, kind.outside) == ("recipe", "stored", True)
