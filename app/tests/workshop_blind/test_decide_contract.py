"""`decide` from its docstring and the Command/Reason contract alone: every command kind accepted, each typed refusal,
the stated order when several apply, undo and redo, and that a decision is a pure function of its input."""

from dataclasses import replace
from types import MappingProxyType

from collections.abc import Callable

import pytest
from ashley.workshop.commands import Added, Command, Edited, Moved, Removed
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Refused, decide
from ashley.workshop.model import Place, Text
from ashley.workshop.rules import Rules
from blind_support import ALANA, RULES, SAM, accepted, add, edit, fold, last, move, reason, remove, undo


def ids(decision: Accepted | Refused) -> list[tuple[int, int]]:
    return [(p.id, p.place.order) for p in decision.state.pieces]


# --- acceptance -----------------------------------------------------------------------------------------------


def test_each_command_kind_is_accepted_on_a_valid_bench() -> None:
    got = fold([add("a"), add("b"), edit(1, 1, "c"), move(2, 0), remove(1), undo(5)])
    assert [type(d).__name__ for d in got] == ["Accepted"] * 6
    assert [d.seq for d in got] == [1, 2, 3, 4, 5, 6]


def test_an_add_goes_last_and_its_id_is_its_seq_at_version_one() -> None:
    got = accepted(last(add("a"), add("b", "x", "doc", "full", SAM)))
    piece = got.state.pieces[1]
    assert (piece.id, piece.kind, piece.text, piece.version, piece.place, piece.changed_by) == (
        2, "doc", Text("b", "x"), 1, Place(1, "full"), 2)
    assert isinstance(got.effect, Added) and got.effect.piece == piece
    assert got.state.next_seq == 3


def test_a_refused_command_still_uses_its_seq_so_the_next_id_skips_it() -> None:
    got = fold([add("a"), add("toolong!"), add("b")])
    assert [d.seq for d in got] == [1, 2, 3]
    assert [p.id for p in got[2].state.pieces] == [1, 3]


@pytest.mark.parametrize("title", ["a", "abcde", " a "])
def test_titles_up_to_the_limit_are_accepted(title: str) -> None:
    assert isinstance(last(add(title)), Accepted) is (len(title) <= 5)


def test_a_body_may_be_empty_and_may_be_exactly_the_kinds_limit() -> None:
    assert isinstance(last(add("a", "")), Accepted)
    assert isinstance(last(add("a", "x" * 10)), Accepted)
    assert isinstance(last(add("a", "x" * 50, kind="doc")), Accepted)


def test_the_body_limit_is_per_kind() -> None:
    assert reason(last(add("a", "x" * 11))) == "too_long"
    assert isinstance(last(add("a", "x" * 11, kind="doc")), Accepted)
    assert reason(last(add("a", "x" * 51, kind="doc"))) == "too_long"


def test_remove_closes_the_gap_and_leaves_other_pieces_untouched() -> None:
    before = fold([add("a"), add("b"), add("c")])[-1]
    got = accepted(last(add("a"), add("b"), add("c"), remove(1)))
    assert ids(got) == [(2, 0), (3, 1)]
    assert isinstance(got.effect, Removed) and got.effect.piece == before.state.pieces[0]
    for after in got.state.pieces:
        was = before.state.piece(after.id)
        assert was is not None and (after.version, after.changed_by) == (was.version, was.changed_by)


def test_a_move_puts_the_piece_at_the_order_and_the_others_shift() -> None:
    got = accepted(last(add("a"), add("b"), add("c"), move(3, 0, "full")))
    assert ids(got) == [(3, 0), (1, 1), (2, 2)]
    assert got.state.pieces[0].place == Place(0, "full") and got.state.pieces[0].changed_by == 4
    assert isinstance(got.effect, Moved) and got.effect.before == Place(2, "small")
    assert [p.changed_by for p in got.state.pieces[1:]] == [1, 2]   # a shift is not a change


def test_a_move_to_the_last_order_is_allowed_and_to_the_next_is_bad_place() -> None:
    setup = [add("a"), add("b"), add("c")]
    assert ids(accepted(fold([*setup, move(1, 2)])[-1])) == [(2, 0), (3, 1), (1, 2)]
    assert reason(fold([*setup, move(1, 3)])[-1]) == "bad_place"


def test_a_move_to_where_it_already_is_changes_only_changed_by() -> None:
    before = last(add("a"), add("b"))
    got = accepted(last(add("a"), add("b"), move(1, 0, "small")))
    assert [p.id for p in got.state.pieces] == [1, 2]
    assert got.state.pieces[0] == replace(before.state.pieces[0], changed_by=3)
    assert got.state.pieces[1] == before.state.pieces[1]


def test_a_move_can_change_only_the_size() -> None:
    got = accepted(last(add("a"), move(1, 0, "large")))
    assert got.state.pieces[0].place == Place(0, "large") and got.state.pieces[0].version == 1


def test_an_edit_replaces_the_text_and_raises_the_version_by_one() -> None:
    got = accepted(last(add("a", "x"), edit(1, 1, "z", "y")))
    piece = got.state.pieces[0]
    assert (piece.text, piece.version, piece.changed_by) == (Text("z", "y"), 2, 2)
    assert isinstance(got.effect, Edited) and (got.effect.before, got.effect.after) == (Text("a", "x"), Text("z", "y"))


def test_an_edit_does_not_change_kind_or_place() -> None:
    got = accepted(last(add("a", kind="doc", size="large"), edit(1, 1)))
    assert (got.state.pieces[0].kind, got.state.pieces[0].place) == ("doc", Place(0, "large"))


# --- refusals -------------------------------------------------------------------------------------------------


def test_an_unknown_kind_is_refused() -> None:
    assert reason(last(add(kind="video"))) == "unknown_kind"


@pytest.mark.parametrize("title", ["", " ", "\t\n ", "abcdef", "      "])
def test_a_bad_title_is_refused_on_add_and_on_edit(title: str) -> None:
    assert reason(last(add(title))) == "bad_title"
    assert reason(last(add("a"), edit(1, 1, title))) == "bad_title"


def test_a_full_bench_refuses_an_add() -> None:
    got = fold([add("a"), add("b"), add("c"), add("d")])
    assert reason(got[-1]) == "full" and len(got[-1].state.pieces) == 3


def test_removing_a_piece_makes_room_again() -> None:
    assert isinstance(fold([add("a"), add("b"), add("c"), remove(2), add("d")])[-1], Accepted)


ON_A_PIECE: list[Callable[[int], Command]] = [lambda pid: remove(pid), lambda pid: move(pid, 0),
                                              lambda pid: edit(pid, 1)]


@pytest.mark.parametrize("make", ON_A_PIECE)
def test_a_command_on_an_unknown_piece_is_no_such_piece(make: Callable[[int], Command]) -> None:
    assert reason(last(add("a"), make(2))) == "no_such_piece"
    assert reason(last(make(1))) == "no_such_piece"


def test_a_removed_piece_is_no_longer_there() -> None:
    assert reason(last(add("a"), remove(1), remove(1))) == "no_such_piece"
    assert reason(last(add("a"), remove(1), edit(1, 1))) == "no_such_piece"


def test_a_pieces_id_is_the_seq_not_its_position() -> None:
    assert reason(last(add("a"), add("b"), remove(1), move(1, 0))) == "no_such_piece"
    assert isinstance(last(add("a"), add("b"), remove(1), move(2, 0)), Accepted)


@pytest.mark.parametrize("base", [0, 1, 3, 4, -1])
def test_an_edit_on_any_base_but_the_current_version_is_stale(base: int) -> None:
    setup = [add("a"), edit(1, 1, "b"), edit(1, 2, "c")]     # version 3
    got = fold([*setup, edit(1, base)])[-1]
    assert isinstance(got, Accepted) if base == 3 else reason(got) == "stale_base"


def test_two_edits_on_one_base_accept_the_first_and_refuse_the_second() -> None:
    got = fold([add("a"), edit(1, 1, "b"), edit(1, 1, "c")])
    assert isinstance(got[1], Accepted) and reason(got[2]) == "stale_base"
    assert got[2].state.pieces[0].text.title == "b"


def test_an_edit_too_long_for_its_kind_is_refused() -> None:
    assert reason(last(add("a"), edit(1, 1, "a", "x" * 11))) == "too_long"
    assert isinstance(last(add("a"), edit(1, 1, "a", "x" * 10)), Accepted)


def test_a_refusal_leaves_the_bench_as_it_was_but_for_next_seq() -> None:
    before = last(add("a"), add("b")).state
    for command in (add(kind="x"), remove(9), move(9, 0), edit(9, 1), edit(1, 7), add("") , undo(99)):
        got = decide(before, command, RULES)
        assert isinstance(got, Refused) and got.seq == before.next_seq
        assert got.state == replace(before, next_seq=before.next_seq + 1)


# --- the stated order when several reasons apply ----------------------------------------------------------------


def test_add_checks_kind_then_title_then_length_then_fullness() -> None:
    full = [add("a"), add("b"), add("c")]
    assert reason(fold([*full, add("", "x" * 99, "video")])[-1]) == "unknown_kind"
    assert reason(fold([*full, add("", "x" * 99)])[-1]) == "bad_title"
    assert reason(fold([*full, add("a", "x" * 99)])[-1]) == "too_long"
    assert reason(fold([*full, add("a")])[-1]) == "full"


def test_move_checks_the_piece_before_the_place() -> None:
    assert reason(last(add("a"), move(9, 5))) == "no_such_piece"


def test_edit_checks_piece_then_stale_base_then_title_then_length() -> None:
    base = [add("a")]
    assert reason(fold([*base, edit(9, 5, "", "x" * 99)])[-1]) == "no_such_piece"
    assert reason(fold([*base, edit(1, 5, "", "x" * 99)])[-1]) == "stale_base"
    assert reason(fold([*base, edit(1, 1, "", "x" * 99)])[-1]) == "bad_title"
    assert reason(fold([*base, edit(1, 1, "a", "x" * 99)])[-1]) == "too_long"


def test_an_edit_of_a_piece_whose_kind_has_left_the_rules_is_unknown_kind_before_anything_else() -> None:
    narrow = Rules(MappingProxyType({"doc": RULES.kinds["doc"]}), max_pieces=3, title_max_chars=5, recent_commands=4, undo_window=100)
    state = fold([add("a", kind="note")]).pop().state
    assert reason(decide(state, edit(1, 9, "", "x" * 99), narrow)) == "unknown_kind"


# --- undo -----------------------------------------------------------------------------------------------------


def test_undoing_an_add_removes_the_piece() -> None:
    got = accepted(last(add("a"), add("b"), undo(1)))
    assert ids(got) == [(2, 0)]


def test_undoing_a_remove_brings_the_piece_back_as_it_was_at_its_old_order() -> None:
    setup = [add("a"), add("b"), edit(1, 1, "z", "q"), add("c"), remove(1)]
    was = fold(setup[:-1])[-1].state.pieces[0]
    got = accepted(last(*setup, undo(5)))
    assert ids(got) == [(1, 0), (2, 1), (4, 2)]
    back = got.state.piece(1)
    assert back is not None and (back.text, back.version, back.place) == (was.text, was.version, was.place)


def test_undoing_a_remove_puts_the_piece_last_when_fewer_pieces_remain() -> None:
    got = accepted(last(add("a"), add("b"), add("c"), remove(3), remove(1), undo(4)))
    assert ids(got) == [(2, 0), (3, 1)]
    got = accepted(last(add("a"), add("b"), add("c"), remove(2), remove(1), remove(3), undo(4)))
    assert ids(got) == [(2, 0)]


def test_undoing_an_edit_restores_the_text_and_the_version_still_rises() -> None:
    got = accepted(last(add("a", "x"), edit(1, 1, "b", "y"), undo(2)))
    piece = got.state.pieces[0]
    assert (piece.text, piece.version) == (Text("a", "x"), 3)


def test_undoing_a_move_returns_the_piece_to_its_earlier_place() -> None:
    got = accepted(last(add("a"), add("b"), add("c"), move(1, 2, "full"), undo(4)))
    assert ids(got) == [(1, 0), (2, 1), (3, 2)] and got.state.pieces[0].place == Place(0, "small")


def test_an_undo_cannot_be_undone_so_there_is_no_redo() -> None:
    assert reason(last(add("a"), undo(1), undo(2))) == "nothing_to_undo"
    assert reason(last(add("a"), edit(1, 1, "b"), undo(2), undo(3))) == "nothing_to_undo"


def test_undoing_twice_undoes_two_commands_in_order_and_an_undone_command_is_not_undone_again() -> None:
    got = fold([add("a"), edit(1, 1, "b"), move(1, 0, "full"), undo(3), undo(2)])
    assert accepted(got[3]).state.pieces[0].place.size == "small" and accepted(got[3]).state.pieces[0].text.title == "b"
    assert accepted(got[4]).state.pieces[0].text.title == "a"
    assert reason(last(add("a"), edit(1, 1, "b"), undo(2), undo(2))) == "changed_since"


def test_an_undo_of_a_refused_later_or_unknown_command_is_nothing_to_undo() -> None:
    assert reason(last(add("toolong!"), undo(1))) == "nothing_to_undo"           # refused
    assert reason(last(add("a"), undo(2))) == "nothing_to_undo"                  # itself
    assert reason(last(add("a"), undo(3))) == "nothing_to_undo"                  # later
    assert reason(last(add("a"), undo(0))) == "nothing_to_undo"
    assert reason(last(add("a"), undo(-4))) == "nothing_to_undo"
    assert reason(last(undo(1))) == "nothing_to_undo"
    assert reason(last(add("a"), undo(1), undo(2), undo(4))) == "nothing_to_undo"


def test_an_undo_after_the_piece_changed_again_is_changed_since() -> None:
    assert reason(last(add("a"), edit(1, 1, "b"), edit(1, 2, "c"), undo(2))) == "changed_since"
    assert reason(last(add("a"), edit(1, 1, "b"), move(1, 0, "full"), undo(2))) == "changed_since"
    assert reason(last(add("a"), move(1, 0, "full"), edit(1, 1, "b"), undo(2))) == "changed_since"
    assert reason(last(add("a"), edit(1, 1, "b"), undo(2), undo(2))) == "changed_since"
    assert reason(last(add("a"), edit(1, 1, "b"), undo(1))) == "changed_since"


def test_an_undo_of_an_add_after_the_piece_was_edited_is_refused() -> None:
    assert reason(last(add("a"), edit(1, 1, "b"), undo(1))) == "changed_since"
    assert reason(last(add("a"), move(1, 0, "large"), undo(1))) == "changed_since"


def test_a_remove_whose_piece_is_back_cannot_be_undone_twice() -> None:
    assert reason(last(add("a"), remove(1), undo(2), undo(2))) == "changed_since"


def test_a_remove_cannot_be_undone_once_the_piece_came_back_changed_and_was_removed_again() -> None:
    assert reason(last(add("a"), remove(1), undo(2), edit(1, 1, "b"), remove(1), undo(2))) == "changed_since"


def test_another_pieces_move_that_shifts_this_one_does_not_count_as_a_change() -> None:
    got = last(add("a"), add("b"), edit(1, 1, "z"), move(2, 0), undo(3))
    assert isinstance(got, Accepted) and got.state.piece(1) is not None
    piece = got.state.piece(1)
    assert piece is not None and piece.text == Text("a", "")


def test_an_undo_that_would_bring_a_piece_back_onto_a_full_bench_is_full() -> None:
    assert reason(last(add("a"), add("b"), add("c"), remove(1), add("d"), undo(4))) == "full"
    assert isinstance(last(add("a"), add("b"), add("c"), remove(1), add("d"), remove(5), undo(4)), Accepted)


def test_undo_checks_nothing_to_undo_then_changed_since_then_full() -> None:
    assert reason(last(add("a"), add("b"), add("c"), remove(1), undo(4), undo(4))) == "changed_since"


def test_undoing_a_remove_on_a_full_bench_does_not_refuse_the_undo_of_an_add() -> None:
    assert isinstance(last(add("a"), add("b"), add("c"), undo(1)), Accepted)


def test_the_author_of_an_undo_need_not_be_the_author_of_what_it_undoes() -> None:
    assert isinstance(last(add("a", by=ALANA), undo(1, SAM)), Accepted)


def test_undo_reads_only_the_entry_it_names() -> None:
    full = last(add("a"), edit(1, 1, "b"), add("c"))
    only = replace(full.state, effects=MappingProxyType({2: full.state.effects[2]}))
    narrow, wide = accepted(decide(only, undo(2), RULES)), accepted(decide(full.state, undo(2), RULES))
    assert (narrow.seq, narrow.effect, narrow.state.pieces) == (wide.seq, wide.effect, wide.state.pieces)


def test_undo_of_a_seq_absent_from_the_effects_is_nothing_to_undo() -> None:
    state = BenchState(pieces=last(add("a")).state.pieces, next_seq=2)
    assert reason(decide(state, undo(1), RULES)) == "nothing_to_undo"


# --- purity ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [add("q"), remove(2), move(1, 1, "full"), edit(2, 1, "n"), edit(2, 5), undo(2),
                                     undo(1), add(kind="zz"), undo(9)])
def test_the_same_input_gives_the_same_output_and_the_input_is_left_alone(command: Command) -> None:
    state = last(add("a"), add("b"), edit(2, 1, "c")).state
    frozen = (state.pieces, state.next_seq, dict(state.effects))
    first = decide(state, command, RULES)
    second = decide(state, command, RULES)
    assert first == second
    assert (state.pieces, state.next_seq, dict(state.effects)) == frozen


def test_the_empty_bench_is_unchanged_by_deciding_against_it() -> None:
    decide(EMPTY, add("a"), RULES)
    decide(EMPTY, remove(1), RULES)
    assert EMPTY.next_seq == 1 and EMPTY.pieces == () and dict(EMPTY.effects) == {}


def test_an_accepted_states_effects_hold_the_new_seq_and_keep_the_old() -> None:
    got = fold([add("a"), add("b"), edit(1, 1, "c")])
    assert sorted(got[-1].state.effects) == [1, 2, 3]
    assert sorted(got[-2].state.effects) == [1, 2]


def test_orders_stay_zero_to_n_minus_one_through_a_run_of_changes() -> None:
    for d in fold([add("a"), add("b"), add("c"), move(3, 0), remove(1), add("d"), move(4, 0, "full"), undo(5)]):
        assert [p.place.order for p in d.state.pieces] == list(range(len(d.state.pieces)))
