"""The bench in her prompt (`Catalogue.now`): its pieces by id and version for a household-text piece, id, kind and
version alone for an outside one; read once per turn; joined by the composite and put in the `moment` layer only."""

import asyncio
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.persona import persona
from ashley.people.model import Household, Person
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.tools.composite import CompositeTools
from ashley.tools.tools import Catalogue
from ashley.workshop.model import Owner, Piece, Place, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop, WorkshopUnavailable
from bench_tools_support import FakeWorkshop

RULES = Rules({"note": Kind("note", "stored", "Note", 4000), "file": Kind("file", "large", "File", 4000, outside=True)},
              max_pieces=10, title_max_chars=40, recent_commands=5, undo_window=100)
CONFIG = BenchToolsConfig(read_body_chars=10, piece_chars=30, recent_commands=2, lead_adds=2)
OWNER = Owner(10, 1)
MARKER = "outside-marker-title"
NOW = datetime(2026, 11, 8, tzinfo=UTC)


def piece(pid: int, kind: str, title: str, version: int = 1, outside: bool = False) -> Piece:
    return Piece(pid, kind, Text(title, "a body of some length"), version, Place(pid, "medium"), pid, outside)


@pytest.fixture
def shop() -> FakeWorkshop:
    fake = FakeWorkshop(pieces=(piece(3, "note", "Plan", version=7), piece(4, "file", MARKER, version=2),
                                piece(5, "note", "Written after outside words", outside=True)))
    services.register(Workshop, fake)
    return fake


def bench_now() -> str | None:
    return asyncio.run(BenchTools(OWNER.household_id, OWNER.person_id, 4, RULES, CONFIG).catalogue()).now


def test_now_names_a_household_piece_by_id_title_and_version(shop: FakeWorkshop) -> None:
    text = bench_now()
    assert text is not None and '"id": 3' in text and '"version": 7' in text and "Plan" in text


def test_an_outside_kind_piece_or_one_written_after_outside_words_shows_id_kind_and_version_only(shop: FakeWorkshop) -> None:
    text = bench_now()
    assert text is not None
    assert MARKER not in text and "Written after outside words" not in text
    assert '{"id": 4, "kind": "file", "version": 2}' in text and '"id": 5' in text


def test_the_bench_is_read_once_however_often_the_catalogue_is_asked(shop: FakeWorkshop) -> None:
    tools = BenchTools(OWNER.household_id, OWNER.person_id, 4, RULES, CONFIG)
    asyncio.run(tools.catalogue())
    asyncio.run(tools.catalogue())
    assert len(shop.reads) == 1


def test_a_bench_that_cannot_be_read_gives_no_view(shop: FakeWorkshop) -> None:
    shop.raises = WorkshopUnavailable()
    assert bench_now() is None


def test_the_composite_joins_each_sources_now_in_source_order(shop: FakeWorkshop) -> None:
    class Told(BenchTools):
        async def catalogue(self) -> Catalogue:
            return Catalogue((), None, now="second")

    joined = CompositeTools({"a": Told(10, 1, 4, RULES, CONFIG), "b": BenchTools(10, 1, 4, RULES, CONFIG)})
    got = asyncio.run(joined.catalogue()).now
    assert got is not None and got.startswith("second\n\n# The bench")


def test_the_view_is_in_the_moment_layer_and_never_the_stable_one() -> None:
    ann = Person(1, 10, "Ann")
    context = persona.Context(now=NOW, household=Household(10, "H", "UTC", "", (ann,)), speaker=ann, home=None, place=None,
                              tool_instructions="how to use tools", tools_reachable=True, tools_now="BENCH-VIEW-TEXT")
    for prompt in persona.system("brainstorm", context).values():
        assert "BENCH-VIEW-TEXT" in prompt.moment and "BENCH-VIEW-TEXT" not in prompt.stable
