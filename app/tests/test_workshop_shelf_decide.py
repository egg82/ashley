"""Archive and Restore from `decide`'s contract: an archived piece leaves the layout and the `max_pieces` count for the
bench's shelf, keeping its text and version; a restore brings it back last at its old size, refused `full` when there is
no room; each is undone by the other, and both survive the codec and replay."""

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import (Add, Archive, Archived, Command, Edit, Move, Remove, Restore, Restored, Run,
                                      Undo, type_of)
from ashley.workshop.decide import Accepted, Decision, Refused, replay
from ashley.workshop.model import HER, By, Piece, Place, Size, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.undo_walk import Step, next_undo

CODE = Kind("code", "stored", "Code", 100, "code", "text")
NOTE = Kind("note", "stored", "Note", 100)
RULES = Rules({"code": CODE, "note": NOTE}, max_pieces=2, title_max_chars=5, recent_commands=10, undo_window=100)
ALANA = By(7)


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def last(*commands: Command) -> Decision:
    return run(*commands)[-1]


def add(title: str = "a", size: Size = "small") -> Add:
    return Add(ALANA, "note", Text(title, title), size)


def laid(decision: Decision) -> list[tuple[int, int]]:
    return [(p.id, p.place.order) for p in decision.state.pieces]


def shelf(decision: Decision) -> list[int]:
    return [p.id for p in decision.state.shelf]


def refused(decision: Decision, reason: str) -> bool:
    return isinstance(decision, Refused) and decision.reason == reason


def test_an_archive_takes_the_piece_off_the_layout_onto_the_shelf_keeping_its_text_and_version() -> None:
    got = last(add("a"), add("b"), Edit(ALANA, 1, 1, Text("a2", "x")), Archive(HER, 1))
    assert isinstance(got, Accepted) and got.seq == 4
    assert laid(got) == [(2, 0)]
    (kept,) = got.state.shelf
    assert (kept.id, kept.text, kept.version, kept.changed_by) == (1, Text("a2", "x"), 2, 4)
    assert isinstance(got.effect, Archived) and got.effect.piece.place == Place(0, "small")


def test_an_archived_piece_leaves_max_pieces_so_another_can_be_added() -> None:
    got = last(add("a"), add("b"), Archive(ALANA, 1), add("c"))
    assert isinstance(got, Accepted)
    assert laid(got) == [(2, 0), (4, 1)] and shelf(got) == [1]


def test_the_shelf_lists_the_most_recently_archived_first() -> None:
    assert shelf(last(add("a"), add("b"), Archive(ALANA, 2), Archive(ALANA, 1))) == [1, 2]


def test_archive_of_a_piece_not_on_the_layout_is_no_such_piece() -> None:
    assert refused(last(add(), Archive(ALANA, 9)), "no_such_piece")
    assert refused(last(add(), Archive(ALANA, 1), Archive(ALANA, 1)), "no_such_piece")
    assert refused(last(add(), Remove(ALANA, 1), Archive(ALANA, 1)), "no_such_piece")


def test_a_shelved_piece_takes_no_edit_move_run_or_remove() -> None:
    shelved = (add(), Archive(ALANA, 1))
    assert refused(last(*shelved, Edit(ALANA, 1, 1, Text("b", ""))), "no_such_piece")
    assert refused(last(*shelved, Move(ALANA, 1, Place(0, "full"))), "no_such_piece")
    assert refused(last(*shelved, Remove(ALANA, 1)), "no_such_piece")
    code = (Add(ALANA, "code", Text("c", "print(1)"), "small"), Archive(ALANA, 1))
    assert refused(last(*code, Run(ALANA, 1, 1, "python")), "no_such_piece")


def test_a_restore_puts_the_piece_last_at_its_old_size_off_the_shelf() -> None:
    got = last(add("a", "full"), add("b"), Archive(ALANA, 1), Restore(HER, 1))
    assert isinstance(got, Accepted) and got.seq == 4
    assert laid(got) == [(2, 0), (1, 1)] and shelf(got) == []
    back = got.state.pieces[1]
    assert (back.place, back.version, back.changed_by) == (Place(1, "full"), 1, 4)
    assert isinstance(got.effect, Restored) and got.effect.piece == back


def test_restore_refusals_in_their_stated_order() -> None:
    assert refused(last(add(), Restore(ALANA, 1)), "no_such_piece")
    assert refused(last(add(), Restore(ALANA, 9)), "no_such_piece")
    assert refused(last(add(), Archive(ALANA, 1), add(), add(), Restore(ALANA, 1)), "full")
    assert refused(last(add(), Archive(ALANA, 1), add(), add(), Restore(ALANA, 9)), "no_such_piece")


def test_undo_of_an_archive_puts_the_piece_back_where_it_was() -> None:
    got = last(add("a"), add("b"), Archive(ALANA, 1), Undo(HER, 3))
    assert isinstance(got, Accepted) and isinstance(got.effect, Restored)
    assert laid(got) == [(1, 0), (2, 1)] and shelf(got) == []
    assert got.state.pieces[0].changed_by == 4


def test_undo_of_an_archive_with_no_room_is_full() -> None:
    assert refused(last(add(), add(), Archive(ALANA, 1), add(), Undo(ALANA, 3)), "full")


def test_undo_of_a_restore_archives_the_piece_again() -> None:
    got = last(add("a"), Archive(ALANA, 1), Restore(ALANA, 1), Undo(ALANA, 3))
    assert isinstance(got, Accepted) and isinstance(got.effect, Archived)
    assert laid(got) == [] and shelf(got) == [1]


def test_undo_reaches_past_neither_an_archive_nor_a_restore_of_the_piece_since() -> None:
    assert refused(last(add("a"), Edit(ALANA, 1, 1, Text("b", "")), Archive(ALANA, 1), Undo(ALANA, 2)), "changed_since")
    assert refused(last(add("a"), Archive(ALANA, 1), Restore(ALANA, 1), Undo(ALANA, 2)), "changed_since")
    assert refused(last(add("a"), Archive(ALANA, 1), Undo(ALANA, 1)), "changed_since")
    assert refused(last(add("a"), Archive(ALANA, 1), Undo(ALANA, 2), Undo(ALANA, 2)), "changed_since")


def test_an_archive_undone_lets_the_change_before_it_be_undone() -> None:
    got = last(add("a"), Edit(ALANA, 1, 1, Text("b", "")), Archive(ALANA, 1), Undo(ALANA, 3), Undo(ALANA, 2))
    assert isinstance(got, Accepted) and got.state.pieces[0].text.title == "a"


def test_undo_walks_archive_and_restore_as_changes() -> None:
    log = [Step(1, True), Step(2, True), Step(3, True)]
    assert next_undo(log) == 3
    assert next_undo([*log, Step(4, True, undid=3)]) == 2


def test_archive_restore_and_their_effects_survive_the_codec() -> None:
    piece = Piece(3, "note", Text("t", "b"), 2, Place(1, "large"), 5)
    for command, name in ((Archive(ALANA, 3), "archive"), (Restore(HER, 3), "restore")):
        assert type_of(command) == name
        assert decode_command(encode_command(command), command.by) == command
    for effect in (Archived(piece), Restored(piece)):
        assert decode_effect(encode_effect(effect)) == effect


def test_replay_rebuilds_the_layout_and_the_shelf() -> None:
    decisions = run(add("a"), add("b"), Archive(ALANA, 1), add("c"), Archive(ALANA, 2), Restore(ALANA, 1),
                    Restore(ALANA, 2))
    assert [d.__class__.__name__ for d in decisions] == ["Accepted"] * 6 + ["Refused"]
    final = decisions[-1]
    assert laid(final) == [(4, 0), (1, 1)] and shelf(final) == [2]
