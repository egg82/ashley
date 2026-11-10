"""Everywhere she is shown something that happened, it carries when, in the household's local time and one format
(`ashley.stamp.stamp`, `Sun 1 Nov 2026 05:00`), never how long ago: remembered and standing facts, the bench's latest
commands, a piece's last change and last run, and the bench reaction's list of changes. A shown line does not depend
on the clock now."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from ashley import services
from ashley.channels.wake.bench_react_turn import said
from ashley.inference.model import ToolCall
from ashley.memory.model import Fact, Recalled
from ashley.people.model import Household
from ashley.people.people import People
from ashley.persona import facts
from ashley.stamp import stamp
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Remove
from ashley.workshop.model import HER, Change, Piece, Place, Text
from ashley.workshop.reactions import Done, Unseen
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Logged, Workshop
from bench_tools_support import FakeWorkshop
from one_home_support import OneHome

DENVER = ZoneInfo("America/Denver")
THEN = datetime(2026, 11, 1, 12, 5, tzinfo=UTC)
LOCAL = "Sun 1 Nov 2026 05:05"
RULES = Rules({"note": Kind("note", "stored", "Note", 4000)}, max_pieces=10, title_max_chars=40, recent_commands=5,
              undo_window=100)
CONFIG = BenchToolsConfig(read_body_chars=10, piece_chars=30, recent_commands=2, lead_adds=2)


def test_a_stamp_is_the_local_weekday_date_and_24_hour_time() -> None:
    assert stamp(THEN, DENVER) == LOCAL
    assert stamp(datetime(2026, 3, 9, 23, 59, tzinfo=DENVER), UTC) == "Tue 10 Mar 2026 05:59"
    assert stamp(datetime(2026, 11, 8, 7, 3, tzinfo=UTC), DENVER) == "Sun 8 Nov 2026 00:03"


def recalled(text: str, learned: datetime, volunteer: bool = True) -> Recalled:
    return Recalled(Fact(7, 1, None, None, "shared", "plan", False, text, 1, learned, None, None), volunteer)


def test_a_remembered_fact_says_when_it_was_learned_in_the_zone_of_now() -> None:
    now = datetime(2026, 11, 22, 9, 0, tzinfo=DENVER)
    got = facts.remembered((recalled("Elodie's mom visits next week", THEN), recalled("tea at six", THEN, False)), now)
    assert got is not None
    assert f"[7] (learned {LOCAL}) Elodie's mom visits next week" in got
    assert f"[7] (learned {LOCAL}) (only if asked) tea at six" in got


def test_a_standing_fact_says_when_it_was_learned() -> None:
    got = facts.standing((recalled("allergic to nuts", THEN),), THEN.astimezone(DENVER))
    assert got is not None and f"[7] (learned {LOCAL}) allergic to nuts" in got


def test_a_fact_line_is_the_same_whenever_it_is_shown() -> None:
    now = datetime(2026, 11, 2, 9, 0, tzinfo=DENVER)
    assert facts.remembered((recalled("x", THEN),), now) == facts.remembered((recalled("x", THEN),),
                                                                             now + timedelta(days=30, minutes=7))


def test_a_fact_with_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError):
        facts.remembered((recalled("x", THEN),), datetime(2026, 11, 2, 9, 0))


def test_the_bench_reaction_gives_each_change_its_time() -> None:
    seen = Unseen(4, 1, 10, 0, 6, 3, (Done(5, "add", 5, "note", THEN - timedelta(hours=2)),
                                      Done(6, "edit", 5, "note", THEN)))
    assert said(seen, DENVER) == ("3 changes on the bench: #5 add note 5 (Sun 1 Nov 2026 03:05), "
                                  "#6 edit note 5 (Sun 1 Nov 2026 05:05) (and 1 earlier)")


@pytest.fixture
def shop() -> Iterator[FakeWorkshop]:
    fake = FakeWorkshop()
    services.register(Workshop, fake)
    services.register(People, OneHome(Household(1, "home", "America/Denver", "", ())))
    yield fake
    services.unregister(People)


def read(shop: FakeWorkshop) -> Any:
    t = BenchTools(1, 10, 4, RULES, CONFIG)
    return json.loads(asyncio.run(t.call(ToolCall("c", "bench_read", {}))).content)


def fill(shop: FakeWorkshop) -> None:
    shop.pieces = (Piece(1, "note", Text("t", "b"), 1, Place(0, "medium"), 2),)
    shop.recent = (Logged(2, THEN, Remove(HER, 1), "accepted", 1),)
    shop.changes = {1: Change(THEN - timedelta(days=3), HER)}


def test_bench_read_stamps_each_recent_command_and_each_piece(shop: FakeWorkshop) -> None:
    fill(shop)
    got = read(shop)
    assert got["recent"][0]["at"] == LOCAL
    assert got["pieces"][0]["changed_at"] == "Thu 29 Oct 2026 06:05"


def test_bench_read_leaves_times_out_when_the_zone_is_not_known(shop: FakeWorkshop) -> None:
    fill(shop)
    services.register(People, OneHome(None))
    got = read(shop)
    assert "at" not in got["recent"][0] and "changed_at" not in got["pieces"][0]
