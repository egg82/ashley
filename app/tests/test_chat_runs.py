"""Which of her turns shows a run: the last non-held turn of hers that records answering the person's turn that asked,
never a held line; and the runs ordered as they ran, with a run lacking a result shown as such."""

from datetime import UTC, datetime

from ashley.api.chat_runs import under_answers
from ashley.conversations.answers import answer_of
from ashley.conversations.model import Turn
from ashley.runs.model import Output, Run

AT = datetime(2026, 10, 30, tzinfo=UTC)


def person(id: int) -> Turn:
    return Turn(id, "person", 1, "q", AT)


def hers(id: int, answers: int | None, follows: bool = False) -> Turn:
    return Turn(id, "ashley", None, "a", AT, follows, answers=answers)


def run(id: int, turn: int, output: Output | None = Output("ran", 0, "3\n", "", False, {"o.txt": "x"}, ("b",))) -> Run:
    return Run(id, 1, 1, turn, f"c{id}", "python", "print(3)", "in", {}, AT, None if output is None else AT, output)


def test_the_answer_is_the_last_of_hers_that_answers_the_person_turn() -> None:
    turns = [person(1), hers(2, 1, follows=True), hers(3, 1), person(4), hers(5, 4)]
    assert answer_of(turns) == {1: 3, 4: 5}


def test_a_person_typing_while_she_works_does_not_take_the_answer_of_the_turn_before() -> None:
    turns = [person(1), hers(2, 1, follows=True), person(3), hers(4, 1), hers(5, 3)]
    assert answer_of(turns) == {1: 4, 3: 5}


def test_answers_out_of_order_still_go_to_the_turn_they_record() -> None:
    turns = [person(1), person(2), hers(3, 2), hers(4, 1)]
    assert answer_of(turns) == {1: 4, 2: 3}


def test_a_held_line_alone_is_no_answer_whether_or_not_the_person_spoke_again() -> None:
    assert answer_of([person(1), hers(2, 1, follows=True)]) == {}
    assert answer_of([person(1), hers(2, 1, follows=True), person(3)]) == {}
    assert answer_of([person(1), hers(2, 1), person(3), hers(4, 3, follows=True)]) == {1: 2}


def test_a_turn_of_hers_that_answers_nothing_answers_no_one() -> None:
    assert answer_of([person(1), hers(2, None), person(3), hers(4, 3)]) == {3: 4}
    assert answer_of([hers(1, None), person(2)]) == {}


def test_an_answer_missing_from_the_turns_leaves_its_person_turn_with_none_not_an_earlier_answer() -> None:
    carried = [person(1), hers(2, 1), person(3), person(5), hers(6, 5)]
    assert answer_of(carried) == {1: 2, 5: 6}
    assert under_answers(carried, [run(7, 3)]) == {}


def test_runs_sit_under_the_answer_in_the_order_they_ran() -> None:
    turns = [person(1), hers(2, 1, follows=True), hers(3, 1), person(4), hers(5, 4)]
    shown = under_answers(turns, [run(9, 4), run(7, 1), run(8, 1)])
    assert {k: [r.id for r in v] for k, v in shown.items()} == {3: [7, 8], 5: [9]}


def test_the_runs_of_the_first_message_sit_under_its_answer_when_the_person_typed_meanwhile() -> None:
    turns = [person(1), hers(2, 1, follows=True), person(3), hers(4, 1), hers(5, 3)]
    shown = under_answers(turns, [run(7, 1), run(8, 3)])
    assert {k: [r.id for r in v] for k, v in shown.items()} == {4: [7], 5: [8]}


def test_a_run_whose_turn_has_no_answer_or_is_not_in_the_conversation_is_shown_nowhere() -> None:
    assert under_answers([person(1), hers(2, 1, follows=True)], [run(1, 1), run(2, 99)]) == {}


def test_a_finished_run_carries_its_result_and_an_unfinished_one_says_it_has_none() -> None:
    done, running = under_answers([person(1), hers(2, 1)], [run(1, 1), run(2, 1, None)])[2]
    assert (done.result, done.exit_code, done.stdout, [(f.name, f.text) for f in done.made], done.skipped) == (
        "ran", 0, "3\n", [("o.txt", "x")], ["b"])
    assert (running.result, running.exit_code, running.finished_at, running.made) == (None, None, None, [])
    assert (running.script, running.stdin) == ("print(3)", "in")
