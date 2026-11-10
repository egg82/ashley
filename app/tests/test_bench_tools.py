"""Her bench tools against a recording Workshop: each command tool builds the Command a person's route would, by her,
on the speaker's bench; a refusal is an error naming its reason; an edit of a piece she has not read whole this turn
is refused before it reaches the Workshop; bodies are cut to length with the cut said; logs carry no title or body."""

import asyncio
import json
import logging
import dataclasses

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_config import BenchToolsConfig
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Add, Archive, Command, Edit, Move, Remove, Restore, Undo
from ashley.workshop.model import HER, By, Change, Owner, Piece, Place, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Applied, BenchClosed, BenchNotFound, Logged, Workshop, WorkshopUnavailable
from bench_tools_support import EPOCH, FakeWorkshop

RULES = Rules({"note": Kind("note", "stored", "Note", 4000), "document": Kind("document", "stored", "Doc", 9000)},
              max_pieces=10, title_max_chars=40, recent_commands=5, undo_window=100)
CONFIG = BenchToolsConfig(read_body_chars=10, piece_chars=30, recent_commands=2, lead_adds=2)
OWNER = Owner(10, 1)
SECRET = "the-secret-shed-plans"


def piece(pid: int, body: str, version: int = 1, order: int = 0) -> Piece:
    return Piece(pid, "note", Text(f"title {pid}", body), version, Place(order, "medium"), pid)


@pytest.fixture
def shop() -> FakeWorkshop:
    fake = FakeWorkshop()
    services.register(Workshop, fake)
    return fake


def tools() -> BenchTools:
    return BenchTools(OWNER.household_id, OWNER.person_id, 4, RULES, CONFIG)


def call(t: BenchTools, name: str, **args: object) -> ToolResult:
    return asyncio.run(t.call(ToolCall("c1", name, args)))


async def calls(t: BenchTools, *asked: tuple[str, dict[str, object]]) -> list[ToolResult]:
    return [await t.call(ToolCall(f"c{i}", name, args)) for i, (name, args) in enumerate(asked)]


def test_the_catalogue_offers_her_bench_tools_with_the_rules_kinds() -> None:
    got = asyncio.run(tools().catalogue())
    names = [s.name for s in got.specs]
    assert names == ["bench_read", "bench_read_piece", "bench_add", "bench_edit", "bench_replace", "bench_move",
                     "bench_remove", "bench_archive", "bench_shelf", "bench_restore", "bench_undo", "bench_rename",
                     "bench_cue", "bench_point"]
    add = next(s for s in got.specs if s.name == "bench_add")
    assert json.loads(json.dumps(add.parameters))["properties"]["kind"]["enum"] == ["note", "document"]
    assert got.instructions is not None and "stale_base" in got.instructions


@pytest.mark.parametrize(("name", "args", "command"), [
    ("bench_add", {"kind": "note", "title": "t", "body": "b", "size": "full"}, Add(HER, "note", Text("t", "b"), "full")),
    ("bench_add", {"kind": "note", "title": "t", "body": "b"}, Add(HER, "note", Text("t", "b"), "medium")),
    ("bench_move", {"piece_id": 3, "order": 0, "size": "small"}, Move(HER, 3, Place(0, "small"))),
    ("bench_remove", {"piece_id": 3}, Remove(HER, 3)),
    ("bench_archive", {"piece_id": 3}, Archive(HER, 3)),
    ("bench_restore", {"piece_id": 3}, Restore(HER, 3)),
    ("bench_undo", {"seq": 5}, Undo(HER, 5)),
])
def test_each_command_tool_applies_her_command_on_the_speakers_bench(shop: FakeWorkshop, name: str,
                                                                      args: dict[str, object], command: Command) -> None:
    got = call(tools(), name, **args)
    assert not got.is_error, got.content
    assert shop.applied == [(OWNER, 4, command)]
    assert json.loads(got.content)["seq"] == 7


def test_an_edit_of_a_piece_read_whole_applies_and_its_new_version_can_be_edited_again(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, "short", version=2),)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read", {}),
                            ("bench_edit", {"piece_id": 3, "base_version": 2, "title": "x", "body": "y"}),
                            ("bench_edit", {"piece_id": 3, "base_version": 3, "title": "x", "body": "z"})))
    assert [r.is_error for r in got] == [False, False, False]
    assert json.loads(got[1].content)["version"] == 3
    assert [c for _, _, c in shop.applied] == [Edit(HER, 3, 2, Text("x", "y")), Edit(HER, 3, 3, Text("x", "z"))]


def test_an_edit_of_a_piece_not_read_whole_this_turn_never_reaches_the_workshop(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, "a body longer than ten"),)
    t = tools()
    got = asyncio.run(calls(t, ("bench_edit", {"piece_id": 3, "base_version": 1, "title": "x", "body": "y"}),
                            ("bench_read", {}),
                            ("bench_edit", {"piece_id": 3, "base_version": 1, "title": "x", "body": "y"})))
    assert [r.is_error for r in got] == [True, False, True]
    assert got[0].content.startswith("unread:") and got[2].content.startswith("unread:")
    assert shop.applied == []


def test_reading_a_piece_whole_lets_her_edit_it(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, "a body longer than ten"),)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3}),
                            ("bench_edit", {"piece_id": 3, "base_version": 1, "title": "x", "body": "y"})))
    assert json.loads(got[0].content)["body"] == "a body longer than ten"
    assert not got[1].is_error and len(shop.applied) == 1


def test_a_piece_longer_than_piece_chars_is_shown_cut_and_cannot_be_edited(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, "x" * 31),)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3}),
                            ("bench_edit", {"piece_id": 3, "base_version": 1, "title": "x", "body": "y"})))
    shown = json.loads(got[0].content)
    assert shown["body"] == "x" * 30 and shown["body_cut"] is True and shown["body_chars"] == 31
    assert got[1].is_error and shop.applied == []


def test_a_piece_she_added_this_turn_she_may_edit_at_version_one(shop: FakeWorkshop) -> None:
    shop.outcome = Applied(8, "accepted", 8)
    t = tools()
    got = asyncio.run(calls(t, ("bench_add", {"kind": "note", "title": "t", "body": "b"}),
                            ("bench_edit", {"piece_id": 8, "base_version": 1, "title": "t", "body": "c"})))
    assert [r.is_error for r in got] == [False, False]


def test_the_read_cuts_bodies_says_so_and_lists_the_latest_commands(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(1, "0123456789"), piece(2, "0123456789X", order=1))
    shop.recent = tuple(Logged(s, EPOCH, Remove(HER, 1), "no_such_piece", None) for s in (1, 2, 3))
    got = json.loads(call(tools(), "bench_read").content)
    assert [(p["id"], p["body"], p["body_cut"]) for p in got["pieces"]] == [(1, "0123456789", False),
                                                                             (2, "0123456789", True)]
    assert [r["seq"] for r in got["recent"]] == [2, 3] and got["recent"][0]["by"] == "you"
    assert got["kinds"]["note"]["max_chars"] == 4000 and got["shelved"] == 0
    assert shop.reads == [(OWNER, 4)]


def test_the_read_says_whether_she_or_a_person_last_changed_each_piece(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(1, "a"), piece(2, "b", order=1), piece(3, "c", order=2))
    shop.changes = {1: Change(EPOCH, HER), 2: Change(EPOCH, By(OWNER.person_id))}
    got = json.loads(call(tools(), "bench_read").content)
    assert [(p["id"], p["last_changed_by"]) for p in got["pieces"]] == [(1, "you"), (2, "person"), (3, "you")]


def test_the_shelf_read_lists_each_archived_piece_without_its_body(shop: FakeWorkshop) -> None:
    shop.shelf = (piece(5, SECRET, version=3), piece(2, "x"))
    assert json.loads(call(tools(), "bench_read").content)["shelved"] == 2
    got = json.loads(call(tools(), "bench_shelf").content)
    assert got == {"bench": 4, "shelf": [{"id": 5, "kind": "note", "title": "title 5", "version": 3},
                                         {"id": 2, "kind": "note", "title": "title 2", "version": 1}]}
    assert shop.applied == []


def test_a_stale_base_comes_back_as_an_error_telling_her_to_read_again(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, "b"),)
    shop.outcome = Applied(9, "stale_base", None)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read", {}),
                            ("bench_edit", {"piece_id": 3, "base_version": 1, "title": "x", "body": "y"})))[1]
    assert got.is_error and got.content.startswith("stale_base:") and "read it again" in got.content


@pytest.mark.parametrize(("raised", "outcome"), [(BenchNotFound(), "not_found"), (BenchClosed(), "closed"),
                                                 (WorkshopUnavailable(), "unavailable")])
def test_a_bench_gone_closed_or_unreachable_is_an_error_naming_it(shop: FakeWorkshop, raised: Exception,
                                                                   outcome: str) -> None:
    shop.raises = raised
    for name, args in (("bench_read", {}), ("bench_remove", {"piece_id": 1})):
        got = call(tools(), name, **args)
        assert got.is_error and got.content.startswith(outcome + ":")


@pytest.mark.parametrize(("name", "args"), [
    ("bench_add", {"kind": "note", "title": 3, "body": "b"}),
    ("bench_add", {"kind": "note", "title": "t", "body": "b", "size": "huge"}),
    ("bench_move", {"piece_id": 1, "order": -1, "size": "small"}),
    ("bench_move", {"piece_id": 1, "order": 0}),
    ("bench_remove", {"piece_id": True}),
    ("bench_archive", {"piece_id": "1"}),
    ("bench_restore", {}),
    ("bench_undo", {}),
    ("bench_read_piece", {"piece_id": "1"}),
])
def test_arguments_of_the_wrong_shape_are_an_error_and_change_nothing(shop: FakeWorkshop, name: str,
                                                                       args: dict[str, object]) -> None:
    got = call(tools(), name, **args)
    assert got.is_error and got.content.startswith("bad_arguments:")
    assert shop.applied == []


def test_a_tool_it_does_not_offer_is_unknown(shop: FakeWorkshop) -> None:
    got = call(tools(), "HassTurnOn")
    assert got.is_error and got.content.startswith("unknown_tool:")


def test_logs_carry_ids_type_and_outcome_never_a_title_or_body(shop: FakeWorkshop,
                                                               caplog: pytest.LogCaptureFixture) -> None:
    shop.pieces = (piece(3, SECRET),)
    caplog.set_level(logging.INFO, "ashley.tools")
    asyncio.run(calls(tools(), ("bench_read", {}), ("bench_read_piece", {"piece_id": 3}),
                      ("bench_add", {"kind": "note", "title": SECRET, "body": SECRET})))
    lines = [r for r in caplog.records if r.getMessage() == "tools.call"]
    fields = [getattr(r, "fields") for r in lines]
    assert [f["outcome"] for f in fields] == ["ok", "ok", "ok"]
    assert fields[2]["command"] == "add" and fields[2]["bench"] == 4 and fields[2]["seq"] == 7
    assert SECRET not in caplog.text and all(SECRET not in str(f) for f in fields)


@pytest.mark.parametrize("name", ["bench_read", "bench_read_piece", "bench_add", "bench_edit", "bench_replace",
                                  "bench_move", "bench_remove", "bench_archive", "bench_shelf", "bench_restore",
                                  "bench_undo"])
def test_an_argument_the_tool_does_not_define_is_an_error_naming_it_and_nothing_is_read_or_applied(
        shop: FakeWorkshop, name: str) -> None:
    own = {"bench_read": {}, "bench_read_piece": {"piece_id": 3},
           "bench_add": {"kind": "note", "title": "t", "body": "b"},
           "bench_edit": {"piece_id": 3, "base_version": 1, "title": "t", "body": "b"},
           "bench_replace": {"piece_id": 3, "base_version": 1, "old": "a", "new": "b"},
           "bench_move": {"piece_id": 3, "order": 0, "size": "small"}, "bench_remove": {"piece_id": 3},
           "bench_archive": {"piece_id": 3}, "bench_shelf": {}, "bench_restore": {"piece_id": 3},
           "bench_undo": {"seq": 1}}[name]
    got = call(tools(), name, **own, by=99)
    assert got.is_error and got.content.startswith("bad_arguments:") and "by" in got.content
    assert shop.applied == [] and shop.reads == []


def test_text_the_workshop_cannot_store_is_an_error_not_an_exception(shop: FakeWorkshop) -> None:
    shop.raises = ValueError("NUL")
    got = call(tools(), "bench_add", kind="note", title="t", body="b")
    assert got.is_error and got.content.startswith("bad_text:")


LONG = "".join(f"line {i:02d}\n" for i in range(12))   # 108 chars, three windows of piece_chars=30 and a bit


def one(t: BenchTools, asked: tuple[str, dict[str, object]]) -> ToolResult:
    return asyncio.run(calls(t, asked))[0]


def replace(pid: int, version: int, old: str, new: str) -> tuple[str, dict[str, object]]:
    return "bench_replace", {"piece_id": pid, "base_version": version, "old": old, "new": new}


def test_a_long_piece_is_read_in_windows_that_say_where_they_are(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG),)
    got = [json.loads(r.content) for r in asyncio.run(calls(
        tools(), ("bench_read_piece", {"piece_id": 3}), ("bench_read_piece", {"piece_id": 3, "offset": 90}),
        ("bench_read_piece", {"piece_id": 3, "offset": 500})))]
    assert (got[0]["body"], got[0]["offset"], got[0]["body_cut"]) == (LONG[:30], 0, True)
    assert (got[1]["body"], got[1]["offset"], got[1]["body_cut"]) == (LONG[90:], 90, False)
    assert got[2]["body"] == "" and got[2]["body_chars"] == len(LONG) and got[2]["body_cut"] is False


@pytest.mark.parametrize("offset", [-1, "3", True, 1.5])
def test_a_window_offset_of_the_wrong_shape_is_an_error(shop: FakeWorkshop, offset: object) -> None:
    shop.pieces = (piece(3, LONG),)
    got = call(tools(), "bench_read_piece", piece_id=3, offset=offset)
    assert got.is_error and got.content.startswith("bad_arguments:") and "offset" in got.content


def test_a_snippet_read_in_a_window_is_replaced_in_a_piece_too_long_to_edit_whole(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG, version=4),)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3, "offset": 60}),
                            replace(3, 4, "line 07\n", "seven\n")))
    assert not got[1].is_error and json.loads(got[1].content)["version"] == 5
    assert [c for _, _, c in shop.applied] == [Edit(HER, 3, 4, Text("title 3", LONG.replace("line 07\n", "seven\n")))]


def test_a_range_edit_leaves_the_new_version_of_a_long_piece_unedited_whole(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG),)
    t = tools()
    first = asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3}), replace(3, 1, "line 01\n", "one\n")))
    shop.pieces = (piece(3, LONG.replace("line 01\n", "one\n"), version=2),)
    got = asyncio.run(calls(t, replace(3, 2, "line 02\n", "two\n"),
                            ("bench_edit", {"piece_id": 3, "base_version": 2, "title": "x", "body": "y"})))
    assert [r.is_error for r in first + got] == [False, False, False, True]
    assert got[1].content.startswith("unread:")


@pytest.mark.parametrize(("old", "why"), [("line 99", "found nowhere"), ("line 0", "found more than once"),
                                          ("", "empty")])
def test_a_snippet_that_does_not_match_exactly_once_is_an_error_and_changes_nothing(shop: FakeWorkshop, old: str,
                                                                                    why: str) -> None:
    shop.pieces = (piece(3, LONG),)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3}), replace(3, 1, old, "x")))[1]
    assert got.is_error and got.content.startswith("bad_arguments:") and shop.applied == []
    assert not old or old not in got.content, why


def test_a_range_edit_of_a_piece_she_has_not_read_is_refused_before_the_workshop(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG),)
    got = one(tools(), replace(3, 1, "line 01\n", "x"))
    assert got.is_error and got.content.startswith("unread:") and shop.applied == []


def test_a_range_edit_based_on_an_older_version_than_the_piece_has_is_stale_and_changes_nothing(
        shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG),)
    t = tools()
    asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3})))
    shop.pieces = (piece(3, LONG, version=2),)
    got = one(t, replace(3, 1, "line 01\n", "x"))
    assert got.is_error and got.content.startswith("stale_base:") and shop.applied == []


def test_a_range_edit_of_a_piece_that_is_gone_is_no_such_piece(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG),)
    t = tools()
    asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3})))
    shop.pieces = ()
    got = one(t, replace(3, 1, "line 01\n", "x"))
    assert got.is_error and got.content.startswith("no_such_piece:") and shop.applied == []


def test_a_range_edit_the_workshop_refuses_comes_back_as_its_reason(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, LONG),)
    shop.outcome = Applied(9, "too_long", None)
    t = tools()
    got = asyncio.run(calls(t, ("bench_read_piece", {"piece_id": 3}), replace(3, 1, "line 01\n", "x")))[1]
    assert got.is_error and got.content.startswith("too_long:")


@pytest.mark.parametrize("args", [{"piece_id": 3, "base_version": 1, "old": "a"},
                                  {"piece_id": 3, "base_version": 1, "old": "a", "new": 4},
                                  {"piece_id": 3, "base_version": "1", "old": "a", "new": "b"}])
def test_a_range_edit_of_the_wrong_shape_is_an_error_and_changes_nothing(shop: FakeWorkshop,
                                                                         args: dict[str, object]) -> None:
    got = call(tools(), "bench_replace", **args)
    assert got.is_error and got.content.startswith("bad_arguments:") and shop.applied == [] and shop.reads == []


def test_the_range_edit_is_offered_and_a_window_offset_is_an_argument_of_the_read() -> None:
    specs = {s.name: s for s in asyncio.run(tools().catalogue()).specs}
    wire = {name: json.loads(json.dumps(s.parameters))["properties"] for name, s in specs.items()}
    assert set(wire["bench_replace"]) == {"piece_id", "base_version", "old", "new"}
    assert "offset" in wire["bench_read_piece"]
    assert specs["bench_replace"].reads is False


def test_a_code_piece_is_added_by_kind_as_the_rules_offer_it() -> None:
    rules = Rules({**RULES.kinds, "code": Kind("code", "stored", "Code", 9000, "code", "text")}, 10, 40, 5, 100)
    t = BenchTools(OWNER.household_id, OWNER.person_id, 4, rules, CONFIG)
    spec = next(s for s in asyncio.run(t.catalogue()).specs if s.name == "bench_add")
    assert "code" in json.loads(json.dumps(spec.parameters))["properties"]["kind"]["enum"]


def lead_tools(adds: int) -> BenchTools:
    return BenchTools(OWNER.household_id, OWNER.person_id, 4, RULES, dataclasses.replace(CONFIG, lead_adds=adds), lead=True)


def add_args(n: int) -> dict[str, object]:
    return {"kind": "note", "title": f"t{n}", "body": "b"}


def test_a_fresh_arrival_turn_adds_at_most_its_cap_and_the_next_is_told_to_ask_first(shop: FakeWorkshop) -> None:
    t = lead_tools(2)
    got = asyncio.run(calls(t, *[("bench_add", add_args(n)) for n in range(3)]))
    assert [r.is_error for r in got] == [False, False, True]
    assert got[2].content.startswith("ask_first:")
    assert [type(c).__name__ for _, _, c in shop.applied] == ["Add", "Add"]


def test_only_a_piece_that_was_accepted_counts_against_the_arrival_cap(shop: FakeWorkshop) -> None:
    t = lead_tools(1)
    shop.outcome = Applied(7, "unknown_kind", None)
    assert call(t, "bench_add", **add_args(0)).content.startswith("unknown_kind:")
    shop.outcome = Applied(8, "accepted", 8)
    assert not call(t, "bench_add", **add_args(1)).is_error
    assert call(t, "bench_add", **add_args(2)).content.startswith("ask_first:")


def test_the_cap_binds_adds_only_and_only_on_a_fresh_arrival(shop: FakeWorkshop) -> None:
    shop.pieces = (piece(3, "short"),)
    capped = lead_tools(1)
    assert not call(capped, "bench_add", **add_args(0)).is_error
    assert not call(capped, "bench_move", piece_id=3, order=0, size="small").is_error
    ordinary = tools()
    got = asyncio.run(calls(ordinary, *[("bench_add", add_args(n)) for n in range(5)]))
    assert not any(r.is_error for r in got)


def test_the_lead_guidance_is_offered_with_its_cap_named() -> None:
    got = asyncio.run(lead_tools(2).catalogue())
    assert got.instructions is not None and "at most 2 pieces" in got.instructions
