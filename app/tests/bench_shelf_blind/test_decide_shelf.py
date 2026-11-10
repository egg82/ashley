"""Archive and Restore through `decide` from the contract alone: what leaves and joins the layout, the shelf's order,
the `max_pieces` count, what a shelved piece takes, and how each is undone."""

import pytest
from ashley.workshop.commands import Archive, Archived, Command, Restore, Restored, Run, piece_of, type_of
from ashley.workshop.decide import EMPTY, Accepted, Refused
from ashley.workshop.model import HER, By, Place
from shelf_support import (ALANA, RULES, SAM, accepted, add, archive, edit, end, fold, ids, last, move, reason,
                           remove, restore, sizes, three)

# --- the commands themselves ----------------------------------------------------------------------------------------


def test_type_of_names_archive_and_restore() -> None:
    assert (type_of(archive(1)), type_of(restore(1))) == ("archive", "restore")
    assert (Archive(ALANA, 4).piece_id, Restore(SAM, 5).piece_id) == (4, 5)


def test_a_new_bench_has_an_empty_shelf() -> None:
    assert EMPTY.shelf == ()
    assert end(*three()).shelf == ()


# --- archive ----------------------------------------------------------------------------------------------------------


def test_archive_takes_the_piece_off_the_layout_and_the_pieces_after_it_move_up() -> None:
    state = end(*three(), archive(2))
    assert ids(state.pieces) == [1, 3]
    assert [p.place.order for p in state.pieces] == [0, 1]
    assert sizes(state.pieces) == ["small", "large"]
    assert ids(state.shelf) == [2]


def test_archive_of_the_first_and_of_the_last_piece() -> None:
    first = end(*three(), archive(1))
    assert ids(first.pieces) == [2, 3] and [p.place.order for p in first.pieces] == [0, 1]
    final = end(*three(), archive(3))
    assert ids(final.pieces) == [1, 2] and [p.place.order for p in final.pieces] == [0, 1]


def test_archive_keeps_the_pieces_text_version_kind_and_size() -> None:
    before = end(*three(), edit(2, 1, "e", "E"))
    piece = before.piece(2)
    assert piece is not None and piece.version == 2
    after = end(*three(), edit(2, 1, "e", "E"), archive(2))
    kept = after.shelf[0]
    assert (kept.id, kept.kind, kept.text, kept.version, kept.place.size) == (2, "note", piece.text, 2, "medium")


def test_archive_effect_is_the_piece_as_it_was_just_before() -> None:
    decisions = fold([*three(), archive(2)])
    done = accepted(decisions[-1])
    before = decisions[-2].state.piece(2)
    assert before is not None
    assert done.seq == 4 and done.effect == Archived(before) and piece_of(done.effect) == 2


def test_archive_leaves_the_other_pieces_version_and_changed_by_alone() -> None:
    before = end(*three())
    after = end(*three(), archive(1))
    for piece_id in (2, 3):
        a, b = before.piece(piece_id), after.piece(piece_id)
        assert a is not None and b is not None
        assert (b.version, b.changed_by, b.text) == (a.version, a.changed_by, a.text)


def test_archive_marks_the_piece_changed_by_the_archive() -> None:
    state = end(*three(), archive(2))
    assert state.shelf[0].changed_by == 4


def test_the_shelf_is_most_recently_archived_first() -> None:
    state = end(*three(), archive(2), archive(3), archive(1))
    assert ids(state.shelf) == [1, 3, 2] and state.pieces == ()


@pytest.mark.parametrize("by", [ALANA, SAM, HER])
def test_anyone_may_archive_and_restore(by: By) -> None:
    state = end(*three(), archive(1, by), restore(1, by))
    assert ids(state.pieces) == [2, 3, 1] and state.shelf == ()


@pytest.mark.parametrize("piece_id", [0, 4, 99, -1])
def test_archive_of_a_piece_that_is_not_on_the_layout_is_no_such_piece(piece_id: int) -> None:
    assert reason(last(*three(), archive(piece_id))) == "no_such_piece"


def test_archive_of_a_shelved_piece_is_no_such_piece() -> None:
    assert reason(last(*three(), archive(2), archive(2))) == "no_such_piece"


def test_archive_of_a_removed_piece_is_no_such_piece() -> None:
    assert reason(last(*three(), remove(2), archive(2))) == "no_such_piece"


def test_archive_on_an_empty_bench_is_no_such_piece() -> None:
    assert reason(last(archive(1))) == "no_such_piece"


def test_a_refused_archive_changes_nothing_but_the_seq() -> None:
    decisions = fold([*three(), archive(2), archive(9)])
    refused, before = decisions[-1], decisions[-2].state
    assert isinstance(refused, Refused) and refused.seq == 5
    assert refused.state.pieces == before.pieces and refused.state.shelf == before.shelf
    assert refused.state.next_seq == 6


# --- restore ----------------------------------------------------------------------------------------------------------


def test_restore_puts_the_piece_last_at_the_size_it_had() -> None:
    state = end(*three(), archive(1), restore(1))
    assert ids(state.pieces) == [2, 3, 1]
    assert [p.place for p in state.pieces] == [Place(0, "medium"), Place(1, "large"), Place(2, "small")]
    assert state.shelf == ()


def test_restore_keeps_text_and_version() -> None:
    state = end(*three(), edit(1, 1, "z", "Z"), archive(1), restore(1))
    piece = state.piece(1)
    assert piece is not None and (piece.text.title, piece.text.body, piece.version) == ("z", "Z", 2)


def test_restore_effect_is_the_piece_as_it_then_was_at_the_place_it_took() -> None:
    done = accepted(last(*three(), archive(1), restore(1)))
    assert isinstance(done.effect, Restored) and piece_of(done.effect) == 1
    assert done.effect.piece.place == Place(2, "small")
    assert done.state.piece(1) == done.effect.piece


def test_restore_marks_the_piece_changed_by_the_restore() -> None:
    state = end(*three(), archive(1), restore(1))
    piece = state.piece(1)
    assert piece is not None and piece.changed_by == 5


def test_restore_takes_the_piece_off_the_shelf_and_leaves_the_rest_in_order() -> None:
    state = end(*three(), archive(1), archive(2), archive(3), restore(2))
    assert ids(state.shelf) == [3, 1] and ids(state.pieces) == [2]


def test_restore_onto_an_empty_layout_is_order_zero() -> None:
    state = end(add("a", size="full"), archive(1), restore(1))
    assert state.pieces[0].place == Place(0, "full")


@pytest.mark.parametrize("piece_id", [0, 2, 99])
def test_restore_of_a_piece_not_on_the_shelf_is_no_such_piece(piece_id: int) -> None:
    assert reason(last(add("a"), restore(piece_id))) == "no_such_piece"


def test_restore_of_a_piece_on_the_layout_is_no_such_piece() -> None:
    assert reason(last(*three(), restore(1))) == "no_such_piece"


def test_restore_of_a_removed_piece_is_no_such_piece() -> None:
    assert reason(last(*three(), remove(1), restore(1))) == "no_such_piece"


def test_restore_twice_refuses_the_second() -> None:
    assert reason(last(*three(), archive(1), restore(1), restore(1))) == "no_such_piece"


def test_restore_onto_a_full_bench_is_full_and_leaves_the_piece_on_the_shelf() -> None:
    decisions = fold([*three(), archive(1), add("d"), restore(1)])
    assert reason(decisions[-1]) == "full"
    state = decisions[-1].state
    assert ids(state.shelf) == [1] and len(state.pieces) == 3


def test_no_such_piece_comes_before_full() -> None:
    assert reason(last(*three(), archive(1), add("d"), restore(99))) == "no_such_piece"


# --- the max_pieces count ---------------------------------------------------------------------------------------------


def test_an_archived_piece_frees_its_slot() -> None:
    assert reason(last(*three(), add("d"))) == "full"
    assert isinstance(last(*three(), archive(2), add("d")), Accepted)


def test_the_shelf_is_not_limited_by_max_pieces() -> None:
    commands: list[Command] = []
    for n in range(RULES.max_pieces + 2):
        commands += [add("x"), archive(2 * n + 1)]
    decisions = fold(commands)
    assert all(isinstance(d, Accepted) for d in decisions)
    assert len(decisions[-1].state.shelf) == RULES.max_pieces + 2 and decisions[-1].state.pieces == ()


def test_layout_and_shelf_together_may_exceed_the_limit() -> None:
    state = end(*three(), archive(1), archive(2), add("d"), add("e"), add("f"))
    assert len(state.pieces) == 3 and len(state.shelf) == 2


def test_an_add_after_an_archive_gets_a_fresh_id_never_the_shelved_ones() -> None:
    state = end(*three(), archive(3), add("d"))
    assert sorted(ids(state.pieces) + ids(state.shelf)) == [1, 2, 3, 5]


# --- a shelved piece takes nothing but a restore ----------------------------------------------------------------------


@pytest.mark.parametrize("command", [edit(2, 1), move(2, 0), remove(2), archive(2)],
                         ids=["edit", "move", "remove", "archive"])
def test_a_shelved_piece_takes_no_edit_move_remove_or_archive(command: Command) -> None:
    decisions = fold([*three(), archive(2), command])
    assert reason(decisions[-1]) == "no_such_piece"
    assert ids(decisions[-1].state.shelf) == [2]


def test_a_shelved_piece_is_removed_by_restoring_it_first() -> None:
    state = end(*three(), archive(2), restore(2), remove(2))
    assert sorted(ids(state.pieces) + ids(state.shelf)) == [1, 3]


def test_a_move_to_the_end_of_the_layout_does_not_count_the_shelf() -> None:
    assert reason(last(*three(), archive(1), move(2, 2))) == "bad_place"
    assert isinstance(last(*three(), archive(1), move(2, 1)), Accepted)


def test_a_shelved_piece_takes_no_run() -> None:
    decisions = fold([*three(), archive(2), Run(ALANA, 2, 1, "python")])
    assert reason(decisions[-1]) == "no_such_piece"


def test_restore_counts_only_the_layout_against_the_limit() -> None:
    state = end(*three(), archive(1), archive(2), add("d"))
    assert len(state.pieces) == 2 and len(state.shelf) == 2
    done = last(*three(), archive(1), archive(2), add("d"), restore(1))
    assert isinstance(done, Accepted) and len(done.state.pieces) == 3 and ids(done.state.shelf) == [2]
