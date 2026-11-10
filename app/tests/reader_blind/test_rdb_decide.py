"""A reader piece and `Point` through `decide` from the contract: which bodies a reader takes, the order of a Point's
refusals, that a point changes no piece, is never undone and is passed over by the undo walk."""

import pytest
from ashley.workshop.commands import Add, Edit, Point, Pointed, Undo, piece_of, type_of
from ashley.workshop.decide import Accepted, BenchState, decide
from ashley.workshop.model import HER, Piece, Place, Text
from ashley.workshop.reader import Passage, body_of
from ashley.workshop.rules import Kind, Rules
from reader_blind_support import (ALANA, LINES, KIND_MAX, RULES, SAM, TEXT, URL, accepted, add_note, add_reader, body, edit_text,
                                  end, fold, last, point, reason, shape)

P = Passage(0, 4, 9)


# --- the reader kind --------------------------------------------------------------------------------------------------


def test_the_reader_kind_is_shipped_with_the_reader_format_and_a_large_limit() -> None:
    kind = RULES.kinds["reader"]
    assert (kind.family, kind.format, kind.max_chars) == ("stored", "reader", KIND_MAX)


def test_an_add_of_a_reader_with_a_page_is_accepted_and_keeps_the_body() -> None:
    state = end(add_reader())
    [piece] = state.pieces
    assert (piece.kind, piece.version, piece.text.body) == ("reader", 1, body())


def test_an_add_of_a_reader_with_an_empty_body_is_a_draft_and_accepted() -> None:
    assert isinstance(last(Add(ALANA, "reader", Text("r", ""), "medium")), Accepted)


@pytest.mark.parametrize("bad", ["words", "{}", '{"url": "https://example.org/", "title": "", "text": "t", "x": 1}',
                                 '{"url": "http://example.org/", "title": "", "text": "t"}', "[]"])
def test_an_add_of_a_reader_with_a_non_empty_body_that_is_no_page_is_bad_reader(bad: str) -> None:
    assert reason(last(Add(ALANA, "reader", Text("r", bad), "medium"))) == "bad_reader"


def test_an_edit_of_a_reader_to_a_bad_body_is_bad_reader_and_to_a_page_is_accepted() -> None:
    assert reason(last(add_reader(), Edit(ALANA, 1, 1, Text("r", "plain words")))) == "bad_reader"
    done = accepted(last(add_reader(), edit_text(1, 1, "new text")))
    piece = done.state.piece(1)
    assert piece is not None and piece.version == 2 and piece.text.body == body("new text")


def test_an_edit_of_a_reader_to_an_empty_body_is_accepted() -> None:
    assert isinstance(last(add_reader(), Edit(ALANA, 1, 1, Text("r", ""))), Accepted)


def test_a_note_may_hold_json_that_is_no_page() -> None:
    assert isinstance(last(Add(ALANA, "note", Text("n", "not a page"), "small")), Accepted)


def test_a_reader_body_over_the_kind_limit_is_too_long_not_bad_reader() -> None:
    long_text = "x" * KIND_MAX
    assert reason(last(add_reader(long_text))) == "too_long"


def test_a_reader_body_at_the_kind_limit_is_accepted() -> None:
    pad = KIND_MAX - len(body(""))
    assert pad > 0 and len(body("x" * pad)) == KIND_MAX
    assert isinstance(last(add_reader("x" * pad)), Accepted)
    assert reason(last(add_reader("x" * (pad + 1)))) == "too_long"


def test_a_bad_reader_body_changes_nothing_and_uses_a_seq() -> None:
    bad = fold([add_reader(), Edit(ALANA, 1, 1, Text("r", "x"))])
    assert reason(bad[-1]) == "bad_reader" and bad[-1].seq == 2
    assert bad[-1].state.pieces == bad[0].state.pieces and bad[-1].state.next_seq == 3


# --- Point accepted ---------------------------------------------------------------------------------------------------


def test_a_point_is_accepted_with_the_pointed_effect_for_the_piece_at_its_version() -> None:
    decisions = fold([add_reader(), point(1, 1, P)])
    done = accepted(decisions[-1])
    assert done.seq == 2 and done.effect == Pointed(1, 1, P) and piece_of(done.effect) == 1
    assert type_of(point(1, 1, P)) == "point"


def test_a_point_changes_no_piece_not_its_version_place_or_changed_by() -> None:
    before = fold([add_reader(), add_note(), edit_text(1, 1, TEXT)])[-1].state
    after = decide(before, point(1, 2, P), RULES)
    assert isinstance(after, Accepted)
    assert tuple(map(shape, after.state.pieces)) == tuple(map(shape, before.pieces))
    assert after.state.shelf == before.shelf and after.state.next_seq == before.next_seq + 1


def test_a_point_by_a_person_and_by_her_are_both_accepted() -> None:
    assert isinstance(last(add_reader(), point(1, 1, P, by=HER)), Accepted)
    assert isinstance(last(add_reader(), point(1, 1, P, by=SAM)), Accepted)


def test_pointing_again_is_accepted_and_clearing_with_none_is_accepted() -> None:
    decisions = fold([add_reader(), point(1, 1, P), point(1, 1, Passage(1, 0, 3)), point(1, 1, None)])
    assert [type(d) for d in decisions] == [Accepted] * 4
    assert accepted(decisions[-1]).effect == Pointed(1, 1, None)


def test_clearing_where_nothing_is_pointed_is_accepted() -> None:
    assert isinstance(last(add_reader(), point(1, 1, None)), Accepted)


@pytest.mark.parametrize("passage", [Passage(0, 0, 15), Passage(1, 0, len(LINES[1])), Passage(3, 5, 9), Passage(1, len(LINES[1]) - 1, len(LINES[1]))])
def test_any_held_passage_is_accepted(passage: Passage) -> None:
    assert isinstance(last(add_reader(), point(1, 1, passage)), Accepted)


def test_a_point_at_an_empty_reader_with_nothing_to_hold_is_a_bad_passage_or_a_clear() -> None:
    draft = Add(ALANA, "reader", Text("r", ""), "medium")
    assert reason(last(draft, point(1, 1, Passage(0, 0, 1)))) == "bad_passage"
    assert isinstance(last(draft, point(1, 1, None)), Accepted)


def test_a_point_after_an_edit_names_the_new_version() -> None:
    assert reason(last(add_reader(), edit_text(1, 1, "other"), point(1, 1, Passage(0, 0, 3)))) == "stale_base"
    assert isinstance(last(add_reader(), edit_text(1, 1, "other text"), point(1, 2, Passage(0, 0, 3))), Accepted)


# --- Point refused, and in which order --------------------------------------------------------------------------------


def test_a_point_at_a_piece_that_is_not_there_is_no_such_piece() -> None:
    assert reason(last(point(9, 1, P))) == "no_such_piece"
    assert reason(last(add_reader(), point(2, 1, P))) == "no_such_piece"
    assert reason(last(add_reader(), point(0, 1, P))) == "no_such_piece"


def test_a_point_at_a_removed_or_shelved_piece_is_no_such_piece() -> None:
    from ashley.workshop.commands import Archive, Remove
    assert reason(last(add_reader(), Remove(ALANA, 1), point(1, 1, P))) == "no_such_piece"
    assert reason(last(add_reader(), Archive(ALANA, 1), point(1, 1, P))) == "no_such_piece"


def test_a_point_at_another_kind_is_not_reader() -> None:
    assert reason(last(add_note("n", "some words here"), point(1, 1, Passage(0, 0, 3)))) == "not_reader"
    assert reason(last(add_note(), point(1, 1, None))) == "not_reader"


def test_a_point_at_a_piece_whose_kind_the_rules_no_longer_know_is_unknown_kind() -> None:
    only_notes = Rules({"note": Kind("note", "stored", "Note", 100)}, 5, 10, 10, 10)
    state = BenchState(pieces=(Piece(1, "reader", Text("r", body()), 1, Place(0, "medium"), 1),), next_seq=2)
    got = decide(state, point(1, 1, P), only_notes)
    assert reason(got) == "unknown_kind"


def test_a_stale_base_is_refused_stale_base() -> None:
    assert reason(last(add_reader(), point(1, 2, P))) == "stale_base"
    assert reason(last(add_reader(), point(1, 0, P))) == "stale_base"
    assert reason(last(add_reader(), point(1, 1, None), point(1, 5, None))) == "stale_base"


def test_a_passage_the_page_does_not_hold_is_bad_passage() -> None:
    for passage in (Passage(0, 3, 3), Passage(0, 9, 4), Passage(0, 0, 16), Passage(9, 0, 1), Passage(0, -1, 2),
                    Passage(-1, 0, 2), Passage(2, 0, 1), Passage(1, 0, len(LINES[1]) + 1)):
        assert reason(last(add_reader(), point(1, 1, passage))) == "bad_passage", passage


def test_the_reasons_are_checked_in_order_no_such_piece_unknown_kind_not_reader_stale_base_bad_passage() -> None:
    bad = Passage(0, 5, 5)
    assert reason(last(point(1, 7, bad))) == "no_such_piece"
    assert reason(last(add_note("n", "text"), point(1, 7, bad))) == "not_reader"
    assert reason(last(add_reader(), point(1, 7, bad))) == "stale_base"
    assert reason(last(add_reader(), point(1, 1, bad))) == "bad_passage"
    only_notes = Rules({"note": Kind("note", "stored", "Note", 100)}, 5, 10, 10, 10)
    state = BenchState(pieces=(Piece(1, "reader", Text("r", body()), 1, Place(0, "medium"), 1),), next_seq=2)
    assert reason(decide(state, point(1, 7, bad), only_notes)) == "unknown_kind"


def test_a_refused_point_changes_no_piece_and_uses_a_seq() -> None:
    decisions = fold([add_reader(), point(1, 1, Passage(0, 2, 2))])
    refused = decisions[-1]
    assert reason(refused) == "bad_passage" and refused.seq == 2
    assert refused.state.pieces == decisions[0].state.pieces and refused.state.next_seq == 3


# --- never undone, passed over by the walk ----------------------------------------------------------------------------


def test_undoing_an_accepted_point_is_nothing_to_undo() -> None:
    assert reason(last(add_reader(), point(1, 1, P), Undo(ALANA, 2))) == "nothing_to_undo"
    assert reason(last(add_reader(), point(1, 1, None), Undo(ALANA, 2))) == "nothing_to_undo"


def test_undoing_a_refused_point_is_nothing_to_undo() -> None:
    assert reason(last(add_reader(), point(1, 1, Passage(0, 5, 5)), Undo(ALANA, 2))) == "nothing_to_undo"


def test_a_point_between_an_edit_and_its_undo_does_not_block_the_undo() -> None:
    commands = [add_reader("first words"), edit_text(1, 1, "second words"), point(1, 2, Passage(0, 0, 6)), Undo(ALANA, 2)]
    done = accepted(last(*commands))
    piece = done.state.piece(1)
    assert piece is not None and piece.text.body == body("first words") and piece.version == 3


def test_undoing_the_add_of_a_reader_after_a_point_is_accepted_and_removes_it() -> None:
    done = accepted(last(add_reader(), point(1, 1, P), Undo(ALANA, 1)))
    assert done.state.pieces == ()


def test_an_undo_after_a_point_leaves_the_pointed_piece_at_a_higher_version() -> None:
    state = end(add_reader("first words"), edit_text(1, 1, "second words"), point(1, 2, Passage(0, 0, 6)), Undo(ALANA, 2))
    piece = state.piece(1)
    assert piece is not None and piece.version == 3
    assert reason(last(add_reader("first words"), edit_text(1, 1, "second words"), point(1, 2, Passage(0, 0, 6)),
                       Undo(ALANA, 2), point(1, 2, Passage(0, 0, 5)))) == "stale_base"


def test_replay_of_commands_with_points_reproduces_the_state() -> None:
    from ashley.workshop.decide import replay
    commands = [add_reader(), point(1, 1, P), edit_text(1, 1, "later"), point(1, 2, Passage(0, 0, 3)), point(1, 2, None)]
    folded = fold(commands)
    replayed = replay(commands, RULES)
    assert [type(d) for d in replayed] == [type(d) for d in folded]
    assert replayed[-1].state.pieces == folded[-1].state.pieces and replayed[-1].seq == folded[-1].seq


def test_url_and_title_ride_in_the_body_so_two_readers_are_independent_pieces() -> None:
    state = end(add_reader("one"), Add(ALANA, "reader", Text("s", body_of("https://example.org/two", "T2", "two")), "small"),
                point(2, 1, Passage(0, 0, 3)))
    assert [p.text.body for p in state.pieces] == [body("one"), body_of("https://example.org/two", "T2", "two")]
    assert URL in state.pieces[0].text.body


def test_a_point_is_not_a_change_for_the_edit_that_follows_at_the_same_version() -> None:
    assert isinstance(last(add_reader(), point(1, 1, P), edit_text(1, 1, "x y z")), Accepted)


def test_type_of_a_point_by_a_person_is_point_and_its_fields_are_kept() -> None:
    p = Point(SAM, 4, 2, P)
    assert (p.by, p.piece_id, p.base_version, p.passage) == (SAM, 4, 2, P)
    assert Pointed(4, 2, None).passage is None
