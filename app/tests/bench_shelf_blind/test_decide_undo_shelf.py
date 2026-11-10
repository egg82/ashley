"""Undo around the shelf through `decide`: an archive is undone by putting the piece back at its old order, a restore by
archiving it again, and undo keeps its `changed_since` and `full` refusals."""

from ashley.workshop.commands import Archived, Restored, Undo, piece_of, type_of
from ashley.workshop.decide import Accepted
from ashley.workshop.model import HER
from shelf_support import SAM, accepted, add, archive, core, edit, end, fold, ids, last, move, reason, remove, restore, shape, three, undo


# --- undo of an archive -----------------------------------------------------------------------------------------------


def test_undo_of_an_archive_puts_the_piece_back_at_its_old_order() -> None:
    before = end(*three())
    state = end(*three(), archive(2), undo(4))
    assert [shape(p) for p in state.pieces] == [shape(p) for p in before.pieces]
    assert state.shelf == ()


def test_undo_of_an_archive_of_the_first_and_of_the_last_piece() -> None:
    before = end(*three())
    for piece_id in (1, 3):
        state = end(*three(), archive(piece_id), undo(4))
        assert [shape(p) for p in state.pieces] == [shape(p) for p in before.pieces]


def test_undo_of_an_archive_is_accepted_as_the_next_seq_with_the_piece_as_its_effect() -> None:
    done = accepted(last(*three(), archive(2), undo(4)))
    assert done.seq == 5 and piece_of(done.effect) == 2


def test_undo_of_an_archive_leaves_the_rest_of_the_shelf() -> None:
    state = end(*three(), archive(1), archive(2), undo(5))
    assert ids(state.shelf) == [1] and sorted(ids(state.pieces)) == [2, 3]


def test_undo_of_an_archive_is_full_when_the_layout_has_no_room() -> None:
    decisions = fold([*three(), archive(2), add("d"), undo(4)])
    assert reason(decisions[-1]) == "full"
    assert ids(decisions[-1].state.shelf) == [2]


def test_undo_of_an_archive_is_possible_once_room_is_made() -> None:
    state = end(*three(), archive(2), add("d"), remove(5), undo(4))
    assert state.shelf == () and ids(state.pieces) == [1, 2, 3]


def test_undo_of_an_archive_goes_last_when_fewer_pieces_remain_than_its_old_order() -> None:
    state = end(*three(), archive(3), remove(2), undo(4))
    assert ids(state.pieces) == [1, 3] and [p.place.order for p in state.pieces] == [0, 1]


def test_undo_of_an_archive_works_after_a_change_to_other_pieces() -> None:
    state = end(*three(), archive(2), edit(1, 1, "z"), undo(4))
    assert sorted(ids(state.pieces)) == [1, 2, 3] and state.shelf == ()


def test_undo_of_an_archive_by_another_person_or_her() -> None:
    for by in (SAM, HER):
        assert isinstance(last(*three(), archive(2), undo(4, by)), Accepted)


def test_an_archive_cannot_be_undone_twice() -> None:
    assert reason(last(*three(), archive(2), undo(4), undo(4))) == "changed_since"


def test_an_undo_of_an_archive_cannot_itself_be_undone() -> None:
    assert reason(last(*three(), archive(2), undo(4), undo(5))) == "nothing_to_undo"


def test_undo_of_an_archive_after_the_piece_was_restored_is_changed_since() -> None:
    assert reason(last(*three(), archive(2), restore(2), undo(4))) == "changed_since"


def test_undo_of_an_archive_after_a_restore_and_archive_again_is_changed_since() -> None:
    assert reason(last(*three(), archive(2), restore(2), archive(2), undo(4))) == "changed_since"
    assert isinstance(last(*three(), archive(2), restore(2), archive(2), undo(6)), Accepted)


# --- undo of a restore ------------------------------------------------------------------------------------------------


def test_undo_of_a_restore_archives_it_again() -> None:
    state = end(*three(), archive(1), restore(1), undo(5))
    assert ids(state.pieces) == [2, 3] and ids(state.shelf) == [1]
    assert state.shelf[0].place.size == "small"


def test_undo_of_a_restore_puts_the_piece_at_the_front_of_the_shelf() -> None:
    state = end(*three(), archive(1), archive(2), restore(1), undo(6))
    assert ids(state.shelf) == [1, 2]


def test_undo_of_a_restore_needs_no_room() -> None:
    assert isinstance(last(*three(), archive(1), restore(1), undo(5)), Accepted)


def test_undo_of_a_restore_after_a_move_is_changed_since() -> None:
    assert reason(last(*three(), archive(1), restore(1), move(1, 0), undo(5))) == "changed_since"


def test_undo_of_a_restore_after_an_edit_is_changed_since() -> None:
    assert reason(last(*three(), archive(1), restore(1), edit(1, 1), undo(5))) == "changed_since"


def test_undo_of_a_restore_then_restore_again_then_undo_the_first_restore_is_changed_since() -> None:
    assert reason(last(*three(), archive(1), restore(1), undo(5), restore(1), undo(5))) == "changed_since"


# --- undo keeps its changed_since refusals around the shelf -----------------------------------------------------------


def test_undo_of_an_add_of_a_shelved_piece_is_changed_since() -> None:
    assert reason(last(*three(), archive(2), undo(2))) == "changed_since"


def test_undo_of_an_edit_before_the_archive_is_changed_since_until_the_archive_is_undone() -> None:
    commands = [*three(), edit(2, 1, "z"), archive(2)]
    assert reason(last(*commands, undo(4))) == "changed_since"
    assert isinstance(last(*commands, undo(5), undo(4)), Accepted)


def test_undo_of_an_edit_before_a_restore_is_changed_since_until_the_restore_is_undone() -> None:
    commands = [*three(), edit(2, 1, "z"), archive(2), restore(2)]
    assert reason(last(*commands, undo(4))) == "changed_since"
    assert isinstance(last(*commands, undo(6)), Accepted)
    assert reason(last(*commands, undo(6), undo(4))) == "changed_since"


def test_undo_of_a_move_before_the_archive_is_changed_since() -> None:
    assert reason(last(*three(), move(1, 2), archive(1), undo(4))) == "changed_since"


def test_undo_of_a_remove_of_a_shelved_piece_cannot_happen_because_remove_refuses() -> None:
    d = last(*three(), archive(1), remove(1))
    assert reason(d) == "no_such_piece"
    assert reason(last(*three(), archive(1), remove(1), undo(5))) == "nothing_to_undo"


def test_undo_of_an_edit_walks_back_after_the_archive_is_undone() -> None:
    state = end(*three(), edit(1, 1, "z", "Z"), archive(1), undo(5), undo(4))
    piece = state.piece(1)
    assert piece is not None and piece.text.title == "a"


def test_undo_of_an_archive_leaves_text_of_a_piece_edited_before() -> None:
    state = end(*three(), edit(1, 1, "z", "Z"), archive(1), undo(5))
    piece = state.piece(1)
    assert piece is not None and (piece.text.title, piece.text.body) == ("z", "Z")


def test_a_refused_restore_or_archive_hides_nothing_from_undo() -> None:
    decisions = fold([*three(), archive(9), restore(9), archive(1), undo(6)])
    assert isinstance(decisions[-1], Accepted)
    assert sorted(ids(decisions[-1].state.pieces)) == [1, 2, 3]
    assert reason(last(*three(), archive(9), undo(4))) == "nothing_to_undo"


def test_undo_of_an_archive_by_a_stale_seq_that_does_not_exist_is_nothing_to_undo() -> None:
    assert reason(last(*three(), archive(1), undo(99))) == "nothing_to_undo"


def test_undo_walk_through_an_archive_and_a_restore_returns_to_the_start() -> None:
    start = end(*three())
    state = end(*three(), archive(2), restore(2), undo(5), undo(4))
    assert [core(p) for p in state.pieces] == [core(p) for p in start.pieces]
    assert state.shelf == ()


def test_the_effect_of_an_undo_of_a_restore_is_the_archive_of_that_piece() -> None:
    done = accepted(last(*three(), archive(1), restore(1), undo(5)))
    assert isinstance(done.effect, Archived) and done.effect.piece.id == 1
    assert isinstance(accepted(last(*three(), archive(1), undo(4))).effect, Restored)


def test_the_undo_type_is_still_undo() -> None:
    assert type_of(undo(1)) == "undo" and isinstance(undo(1), Undo)


