"""`next_undo`: the command a press of Undo names, walked over the log newest first."""

from ashley.workshop.undo_walk import Step, next_undo


def test_an_empty_log_has_nothing_to_undo() -> None:
    assert next_undo([]) is None


def test_the_newest_accepted_command_comes_first_and_refused_ones_are_passed_over() -> None:
    assert next_undo([Step(1, True), Step(2, True), Step(3, False)]) == 2


def test_each_undo_moves_the_target_one_older_and_an_undone_command_is_skipped() -> None:
    log = [Step(1, True), Step(2, True), Step(3, True)]
    assert next_undo(log) == 3
    log.append(Step(4, True, undid=3))
    assert next_undo(log) == 2
    log.append(Step(5, True, undid=2))
    assert next_undo(log) == 1
    log.append(Step(6, True, undid=1))
    assert next_undo(log) is None


def test_a_refused_undo_does_not_count_as_undone() -> None:
    assert next_undo([Step(1, True), Step(2, False, undid=1)]) == 1


def test_an_undo_is_never_the_target() -> None:
    assert next_undo([Step(1, True, undid=9)]) is None
