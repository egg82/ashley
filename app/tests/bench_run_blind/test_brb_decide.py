"""The Run command from `decide`'s contract: accepted for a code piece at the version named, refused in the stated
order, changing no piece, never undone, never in the way of undoing the change around it."""

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import REASONS, Edit, Ran, Remove, Run, Undo, type_of
from ashley.workshop.decide import EMPTY, Accepted, decide
from ashley.workshop.model import HER as HER_BY
from ashley.workshop.model import Text
from ashley.workshop.undo_walk import Step, next_undo
from brb_support import ALANA, NO_CODE, RULES, accepted, add_code, add_note, fold, reason, run_cmd


def test_run_is_a_command_of_type_run_and_not_runnable_is_a_reason() -> None:
    assert type_of(run_cmd(1)) == "run" and "not_runnable" in REASONS


def test_a_run_of_a_code_piece_at_its_version_is_accepted_as_ran() -> None:
    [_, ran] = fold(add_code(), run_cmd(1, 1))
    got = accepted(ran)
    assert got.effect == Ran(1, 1) and got.seq == 2


def test_the_effect_names_the_version_that_ran() -> None:
    ds = fold(add_code(), Edit(ALANA, 1, 1, Text("c", "print(2)")), run_cmd(1, 2))
    assert accepted(ds[-1]).effect == Ran(1, 2)


def test_a_run_changes_no_piece() -> None:
    [_, before, after] = fold(add_code(), Edit(ALANA, 1, 1, Text("c", "x")), run_cmd(1, 2, by=HER_BY))
    assert after.state.pieces == before.state.pieces
    [piece] = after.state.pieces
    assert (piece.version, piece.changed_by) == (2, 2)


def test_a_run_uses_a_seq_and_is_recorded_in_effects() -> None:
    ds = fold(add_code(), run_cmd(1), run_cmd(1))
    assert [accepted(d).seq for d in ds] == [1, 2, 3]
    assert ds[-1].state.next_seq == 4 and ds[-1].state.effects[3] == Ran(1, 1)


def test_the_same_version_can_be_run_again() -> None:
    ds = fold(add_code(), run_cmd(1), run_cmd(1))
    assert isinstance(ds[2], Accepted)


def test_decide_does_not_judge_the_language() -> None:
    assert isinstance(fold(add_code(), run_cmd(1, language="cobol"))[1], Accepted)


def test_no_such_piece() -> None:
    assert reason(fold(run_cmd(1))[0]) == "no_such_piece"
    assert reason(fold(add_code(), run_cmd(2))[1]) == "no_such_piece"


def test_a_removed_piece_cannot_be_run() -> None:
    assert reason(fold(add_code(), Remove(ALANA, 1), run_cmd(1))[2]) == "no_such_piece"


def test_no_such_piece_comes_before_a_stale_base() -> None:
    assert reason(fold(add_code(), run_cmd(9, base_version=99))[1]) == "no_such_piece"


def test_a_note_is_not_runnable() -> None:
    assert reason(fold(add_note(), run_cmd(1))[1]) == "not_runnable"


def test_not_runnable_comes_before_a_stale_base() -> None:
    assert reason(fold(add_note(), run_cmd(1, base_version=5))[1]) == "not_runnable"


def test_a_stale_base_is_refused_for_an_older_and_a_newer_version() -> None:
    ds = fold(add_code(), Edit(ALANA, 1, 1, Text("c", "y")), run_cmd(1, 1), run_cmd(1, 3))
    assert [reason(ds[2]), reason(ds[3])] == ["stale_base", "stale_base"]


def test_a_kind_the_rules_no_longer_hold_is_unknown_kind_before_the_rest() -> None:
    first = accepted(fold(add_code())[0])
    for base in (1, 7):
        got = decide(first.state, run_cmd(1, base_version=base), NO_CODE)
        assert reason(got) == "unknown_kind"


def test_a_refused_run_uses_a_seq_and_changes_nothing() -> None:
    [_, bad] = fold(add_code(), run_cmd(1, base_version=4))
    assert bad.state.next_seq == 3 and bad.state.pieces == fold(add_code())[0].state.pieces


def test_anyone_may_run_a_piece_of_anyone() -> None:
    for who in (ALANA, HER_BY):
        assert isinstance(fold(add_code(), run_cmd(1, by=who))[1], Accepted)


# --- undo ----------------------------------------------------------------------------------------------------------


def test_undo_naming_a_run_is_nothing_to_undo() -> None:
    ds = fold(add_code(), run_cmd(1), Undo(ALANA, 2))
    assert reason(ds[2]) == "nothing_to_undo"


def test_a_refused_undo_of_a_run_changes_no_piece() -> None:
    ds = fold(add_code(), run_cmd(1), Undo(ALANA, 2))
    assert ds[2].state.pieces == ds[1].state.pieces


def test_a_run_does_not_stop_the_undo_of_the_edit_before_it() -> None:
    ds = fold(add_code("a"), Edit(ALANA, 1, 1, Text("c", "b")), run_cmd(1, 2), Undo(ALANA, 2))
    got = accepted(ds[3])
    [piece] = got.state.pieces
    assert piece.text.body == "a" and piece.version == 3


def test_a_run_does_not_stop_the_undo_of_the_add_before_it() -> None:
    ds = fold(add_code(), run_cmd(1), Undo(ALANA, 1))
    assert accepted(ds[2]).state.pieces == ()


def test_a_run_between_two_edits_does_not_make_the_first_changed_since() -> None:
    ds = fold(add_code("a"), Edit(ALANA, 1, 1, Text("c", "b")), run_cmd(1, 2), Edit(ALANA, 1, 2, Text("c", "c")),
              Undo(ALANA, 4), Undo(ALANA, 2))
    assert isinstance(ds[4], Accepted) and isinstance(ds[5], Accepted)
    assert ds[5].state.pieces[0].text.body == "a"


def test_a_run_after_an_undo_of_an_edit_does_not_block_a_later_undo_of_the_add() -> None:
    ds = fold(add_code(), Edit(ALANA, 1, 1, Text("c", "z")), Undo(ALANA, 2), run_cmd(1, 3), Undo(ALANA, 1))
    assert isinstance(ds[4], Accepted)


def test_the_codec_round_trips_a_run_and_its_effect() -> None:
    command = run_cmd(3, 4, "python", by=HER_BY)
    assert decode_command(encode_command(command), HER_BY) == command
    assert decode_effect(encode_effect(Ran(3, 4))) == Ran(3, 4)


def test_a_run_on_an_empty_bench_is_no_such_piece() -> None:
    assert reason(decide(EMPTY, Run(ALANA, 1, 1, "python"), RULES)) == "no_such_piece"


# --- the walk ------------------------------------------------------------------------------------------------------


def test_the_walk_passes_over_an_accepted_run() -> None:
    assert next_undo([Step(1, True), Step(2, True), Step(3, True, run=True)]) == 2


def test_the_walk_passes_over_several_runs_and_a_refused_one() -> None:
    log = [Step(1, True), Step(2, True, run=True), Step(3, False, run=True), Step(4, True, run=True)]
    assert next_undo(log) == 1


def test_a_log_of_only_runs_has_nothing_to_undo() -> None:
    assert next_undo([Step(1, True, run=True), Step(2, True, run=True)]) is None


def test_an_undo_of_the_change_before_a_run_then_leaves_nothing() -> None:
    log = [Step(1, True), Step(2, True, run=True), Step(3, True, undid=1)]
    assert next_undo(log) is None


def test_a_run_after_an_undo_does_not_bring_the_undone_change_back() -> None:
    log = [Step(1, True), Step(2, True), Step(3, True, undid=2), Step(4, True, run=True)]
    assert next_undo(log) == 1
