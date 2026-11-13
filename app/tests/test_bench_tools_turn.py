"""Her bench tools and turns: a change of hers carries the turn the tools were built for, and `bench_undo` with
`whole_turn` hands the turn's undo to the Workshop as one group, naming each refusal."""

import asyncio
import dataclasses
import json

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Remove
from ashley.workshop.model import HER, Owner
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import TurnUndone, Workshop
from bench_tools_support import FakeWorkshop

RULES = Rules({"note": Kind("note", "stored", "Note", 4000)}, max_pieces=10, title_max_chars=40, recent_commands=5,
              undo_window=100)
CONFIG = BenchToolsConfig(read_body_chars=10, piece_chars=30, recent_commands=2, lead_adds=2)
OWNER = Owner(10, 1)


@pytest.fixture
def shop() -> FakeWorkshop:
    fake = FakeWorkshop()
    services.register(Workshop, fake)
    return fake


def built(turn_id: int | None = None) -> BenchTools:
    return BenchTools(OWNER.household_id, OWNER.person_id, 4, RULES, CONFIG, turn_id=turn_id)


def call(t: BenchTools, name: str, **args: object) -> ToolResult:
    return asyncio.run(t.call(ToolCall("c1", name, args)))


def test_a_change_of_hers_carries_the_turn_the_tools_were_built_for(shop: FakeWorkshop) -> None:
    assert not call(built(12), "bench_remove", piece_id=3).is_error
    assert shop.applied == [(OWNER, 4, Remove(dataclasses.replace(HER, turn=12), 3))]


def test_undo_with_whole_turn_undoes_the_turn_together_by_her_in_this_turn(shop: FakeWorkshop) -> None:
    got = call(built(12), "bench_undo", seq=5, whole_turn=True)
    assert not got.is_error and json.loads(got.content) == {"undone": [3, 2]}
    assert shop.turn_undos == [(dataclasses.replace(HER, turn=12), 5)] and shop.applied == []


def test_a_refused_turn_undo_is_an_error_naming_each_refusal(shop: FakeWorkshop) -> None:
    shop.turn_undone = TurnUndone((), ((3, "changed_since"), (2, "nothing_to_undo")))
    got = call(built(), "bench_undo", seq=5, whole_turn=True)
    assert got.is_error and got.content.startswith("changed_since: nothing was undone")
    assert "seq 3 changed_since" in got.content and "seq 2 nothing_to_undo" in got.content


def test_whole_turn_is_true_or_false(shop: FakeWorkshop) -> None:
    assert call(built(), "bench_undo", seq=5, whole_turn="yes").content.startswith("bad_arguments")
    assert shop.turn_undos == []
