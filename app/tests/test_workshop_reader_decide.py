"""A reader piece's body and a Point at it, from `decide`'s contract: a page is exactly url, title and text; a passage is
a non-empty range inside one paragraph; a Point is accepted only at the version it names, changes no piece, is never
undone and never in the way of undoing the change before it; the codec keeps a Point and its effect."""

import json
from pathlib import Path

from ashley.workshop import reader
from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import Add, Command, Edit, Point, Pointed, Undo, type_of
from ashley.workshop.decide import Accepted, Decision, Refused, decide, replay
from ashley.workshop.model import HER, By, Text
from ashley.workshop.reader import Passage
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.undo_walk import Step, next_undo

READER = Kind("reader", "stored", "Reader", 500, "reader")
NOTE = Kind("note", "stored", "Note", 100)
RULES = Rules({"reader": READER, "note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
ALANA = By(7)
PAGE = reader.body_of("https://a.example/x", "T", "first line\nsecond line\nthird")


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def test_a_transcript_names_its_recording_and_one_start_for_each_line() -> None:
    lines = "[0:00] a\n[0:09] b"
    good = reader.body_of("", "T", lines, reader.Recording(3, (0.0, 9.25)))
    assert reader.well_formed(good)
    found = reader.page_of(good)
    assert found is not None and found.recording == reader.Recording(3, (0.0, 9.25))
    plain = reader.page_of(PAGE)
    assert plain is not None and plain.recording is None
    for bad in ('{"piece_id": 3, "starts": [0, "x"]}', '{"piece_id": 3, "starts": [0, -1]}',
                '{"piece_id": true, "starts": [0, 1]}', '{"piece_id": 3}', '{"piece_id": 3, "starts": [0, 1], "x": 1}'):
        body = '{"url": "", "title": "T", "text": %s, "recording": %s}' % (json.dumps(lines), bad)
        assert reader.well_formed(body), bad
        parsed = reader.page_of(body)
        assert parsed is not None and parsed.recording is None, bad
    short = reader.body_of("", "T", lines, reader.Recording(3, (0.0,)))
    parsed = reader.page_of(short)
    assert parsed is not None and parsed.recording is None


def page() -> Add:
    return Add(HER, "reader", Text("p", PAGE), "large")


def test_a_body_is_empty_or_exactly_a_page() -> None:
    assert reader.well_formed("") and reader.well_formed(PAGE)
    for bad in ("not json", "[]", '{"url": "https://a.example/"}',
                '{"url": "http://a.example/", "title": "", "text": ""}',
                '{"url": "https://a.example/", "title": 1, "text": ""}',
                '{"url": "https://a.example/", "title": "", "text": "", "more": 1}'):
        assert not reader.well_formed(bad), bad
        got = run(Add(HER, "reader", Text("p", bad), "large"))[-1]
        assert isinstance(got, Refused) and got.reason == "bad_reader"


def test_a_quote_is_located_only_where_it_occurs_once_inside_a_paragraph() -> None:
    found = reader.page_of(PAGE)
    assert found is not None and found.paragraphs == ("first line", "second line", "third")
    assert reader.locate(found, "second") == Passage(1, 0, 6)
    assert reader.locate(found, "line") is None
    assert reader.locate(found, "line\nsecond") is None
    assert reader.locate(found, "") is None
    assert reader.locate(found, "nowhere") is None
    assert reader.locate(found, "ird") == Passage(2, 2, 5)


def test_a_passage_is_held_only_when_it_is_a_nonempty_range_inside_a_paragraph() -> None:
    found = reader.page_of(PAGE)
    assert found is not None
    assert reader.holds(found, Passage(0, 0, 10)) and reader.holds(found, Passage(2, 4, 5))
    for bad in (Passage(0, 0, 11), Passage(3, 0, 1), Passage(-1, 0, 1), Passage(0, 3, 3), Passage(0, 5, 2),
                Passage(0, -1, 2)):
        assert not reader.holds(found, bad), bad


def test_a_point_is_accepted_at_the_version_it_names_and_changes_no_piece() -> None:
    added, pointed = run(page(), Point(HER, 1, 1, Passage(1, 0, 6)))
    assert isinstance(pointed, Accepted) and pointed.effect == Pointed(1, 1, Passage(1, 0, 6))
    assert pointed.state.pieces == added.state.pieces
    cleared = run(page(), Point(HER, 1, 1, None))[-1]
    assert isinstance(cleared, Accepted) and cleared.effect == Pointed(1, 1, None)


def test_point_refusals_in_their_stated_order() -> None:
    assert refusal(page(), Point(HER, 9, 1, None)) == "no_such_piece"
    assert refusal(Add(HER, "note", Text("n", "x"), "small"), Point(HER, 1, 1, None)) == "not_reader"
    assert refusal(page(), Point(HER, 1, 2, Passage(0, 0, 1))) == "stale_base"
    assert refusal(page(), Point(HER, 1, 1, Passage(0, 0, 99))) == "bad_passage"
    assert refusal(Add(HER, "reader", Text("p", ""), "small"), Point(HER, 1, 1, Passage(0, 0, 1))) == "bad_passage"
    added = run(page())[-1]
    without = Rules({"note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
    unknown = decide(added.state, Point(HER, 1, 1, None), without)
    assert isinstance(unknown, Refused) and unknown.reason == "unknown_kind"


def refusal(add: Add, point: Point) -> str:
    got = run(add, point)[-1]
    assert isinstance(got, Refused)
    return got.reason


def test_a_point_is_never_undone() -> None:
    got = run(page(), Point(HER, 1, 1, Passage(0, 0, 3)), Undo(ALANA, 2))[-1]
    assert isinstance(got, Refused) and got.reason == "nothing_to_undo"


def test_a_point_does_not_stand_in_the_way_of_undoing_the_edit_before_it() -> None:
    other = reader.body_of("https://a.example/y", "U", "other")
    got = run(page(), Edit(ALANA, 1, 1, Text("p", other)), Point(HER, 1, 2, Passage(0, 0, 3)), Undo(ALANA, 2))[-1]
    assert isinstance(got, Accepted) and got.state.pieces[0].text.body == PAGE


def test_undo_walks_past_a_point() -> None:
    assert next_undo([Step(1, True), Step(2, True, run=True)]) == 1


def test_a_point_and_its_effect_survive_the_codec() -> None:
    for passage in (Passage(2, 1, 4), None):
        point, effect = Point(HER, 3, 2, passage), Pointed(3, 2, passage)
        assert type_of(point) == "point"
        assert decode_command(encode_command(point), HER) == point
        assert decode_effect(encode_effect(effect)) == effect


def test_the_shared_passages_are_where_the_server_locates_them() -> None:
    """`reader_passages.json` is also read by the client's `passage.test.ts`, which cuts each paragraph at these
    offsets and must get the quote back."""
    shared = json.loads((Path(__file__).parent / "reader_passages.json").read_text(encoding="utf-8"))
    found = reader.Page("https://a.example/x", "T", shared["text"])
    assert len(shared["cases"]) >= 4 and any(not c["quote"].isascii() for c in shared["cases"])
    for case in shared["cases"]:
        assert reader.locate(found, case["quote"]) == Passage(case["paragraph"], case["start"], case["end"]), case
