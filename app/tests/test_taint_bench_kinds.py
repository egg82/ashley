"""`kinds.json` marks the piece kinds whose text is written outside the household, and a bench read narrows its
result's `outside` by the kinds it shows: false unless a shown piece is of such a kind."""

import asyncio
import json
from pathlib import Path

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Piece, Place, Text
from ashley.workshop.rules import Kind, Rules, kinds_from
from ashley.workshop.workshop import Workshop
from bench_tools_support import FakeWorkshop

KINDS = json.loads((Path(workshop_rules.__file__).with_name("kinds.json")).read_text())
OUTSIDE = {"file", "site", "reader", "recipe", "video", "clip", "audio", "image"}
RULES = Rules({"note": Kind("note", "stored", "Note", 4000), "reader": Kind("reader", "stored", "Reader", 9000, "reader",
                                                                          None, True)},
              max_pieces=10, title_max_chars=40, recent_commands=5, undo_window=100)
CONFIG = BenchToolsConfig(read_body_chars=10, piece_chars=30, recent_commands=2, lead_adds=2)


def piece(pid: int, kind: str) -> Piece:
    return Piece(pid, kind, Text(f"t{pid}", "body"), 1, Place(pid, "medium"), pid)


def call(name: str, **args: object) -> ToolResult:
    return asyncio.run(BenchTools(1, 10, 4, RULES, CONFIG).call(ToolCall("c1", name, args)))


@pytest.fixture
def shop() -> FakeWorkshop:
    fake = FakeWorkshop()
    services.register(Workshop, fake)
    return fake


def test_the_shipped_kinds_mark_exactly_the_outside_ones() -> None:
    rules = workshop_rules.load()
    assert {k for k, v in rules.kinds.items() if v.outside} == OUTSIDE
    assert set(rules.kinds) > OUTSIDE, "control: kinds that are not outside exist"


def test_a_kind_says_outside_with_a_boolean_or_not_at_all() -> None:
    assert not kinds_from({"n": {"family": "stored", "label": "N", "max_chars": 5, "format": "plain"}})["n"].outside
    with pytest.raises(ValueError):
        kinds_from({"n": {"family": "stored", "label": "N", "max_chars": 5, "format": "plain", "outside": "yes"}})


def test_a_kind_the_rules_do_not_have_counts_as_outside() -> None:
    assert RULES.shows_outside(["note", "gone"]) and not RULES.shows_outside(["note"])


def test_a_bench_of_notes_read_is_not_outside(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(1, "note"),)
    assert call("bench_read").outside is False
    assert call("bench_read_piece", piece_id=1).outside is False


def test_a_reader_piece_makes_the_read_outside(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(1, "note"), piece(2, "reader"))
    assert call("bench_read").outside is True
    assert call("bench_read_piece", piece_id=2).outside is True
    assert call("bench_read_piece", piece_id=1).outside is False, "control: the note alone is not"


def test_the_shelf_is_judged_by_the_pieces_on_it(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(1, "reader"),)
    shop.shelf = (piece(3, "note"),)
    assert call("bench_shelf").outside is False
    shop.shelf = (piece(3, "reader"),)
    assert call("bench_shelf").outside is True


def test_a_change_result_leaves_outside_to_its_spec(shop: FakeWorkshop) -> None:
    assert call("bench_remove", piece_id=3).outside is None
