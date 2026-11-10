"""`wire` and `under_answers`: a stored run as the page reads it, and which of her turns carries which runs."""

import pytest
from ashley.api.chat_runs import under_answers, wire
from ashley.api.run_models import ChatRun
from ashley.runs.model import BenchRun, Output
from cr_support import AT, ids, run, turns


def test_a_run_with_a_result_is_served_whole() -> None:
    got = wire(run(3, 1))
    assert (got.id, got.language, got.script, got.stdin) == (3, "python", "script 3", "in")
    assert (got.started_at, got.finished_at) == (AT, run(3, 1).finished_at)
    assert (got.result, got.exit_code, got.stdout, got.stderr, got.cut) == ("ran", 0, "out", "err", False)
    assert [(f.name, f.text) for f in got.made] == [("r.txt", "é")] and got.skipped == ["b.bin"]


def test_a_run_with_no_recorded_result_has_a_null_result_and_empty_streams() -> None:
    got = wire(run(3, 1, output=None))
    assert got.result is None and got.exit_code is None and got.finished_at is None
    assert (got.stdout, got.stderr, got.cut, got.made, got.skipped) == ("", "", False, [], [])
    assert (got.script, got.stdin) == ("script 3", "in")
    assert '"result":null' in got.model_dump_json()


@pytest.mark.parametrize("output", [Output("timed_out", None, "partial", ""), Output("out_of_memory", None, "", "", True),
                                    Output("failed", None, "", "boom"), Output("ran", 3, "o", "e"),
                                    Output("unknown", None, "", "")])
def test_every_outcome_is_served_as_the_result_with_its_streams(output: Output) -> None:
    got = wire(run(1, 1, output))
    assert (got.result, got.exit_code, got.stdout, got.stderr, got.cut) == (
        output.outcome, output.exit_code, output.stdout, output.stderr, output.cut)


def test_the_files_a_run_made_keep_their_names_and_texts_in_order() -> None:
    got = wire(run(1, 1, Output("ran", 0, "", "", False, {"b.txt": "2", "a.txt": "1"}, ("x.bin", "y.bin"))))
    assert [(f.name, f.text) for f in got.made] == [("b.txt", "2"), ("a.txt", "1")]
    assert got.skipped == ["x.bin", "y.bin"]


def test_the_wire_run_is_a_chat_run() -> None:
    assert isinstance(wire(run(1, 1)), ChatRun)


def test_runs_go_under_the_answer_to_the_person_turn_that_asked() -> None:
    assert ids(under_answers(turns("pa"), [run(1, 1)])) == {2: [1]}


def test_a_held_line_carries_no_run_the_answer_after_it_does() -> None:
    shown = under_answers(turns("pha"), [run(1, 1), run(2, 1)])
    assert ids(shown) == {3: [1, 2]} and not shown.get(2)


def test_runs_stay_in_the_order_they_were_given() -> None:
    assert ids(under_answers(turns("pa"), [run(4, 1), run(5, 1), run(9, 1)])) == {2: [4, 5, 9]}


def test_each_answer_carries_only_the_runs_of_its_own_person_turn() -> None:
    shown = under_answers(turns("papa"), [run(1, 1), run(2, 3), run(3, 1), run(4, 3)])
    assert ids(shown) == {2: [1, 3], 4: [2, 4]}


def test_a_run_waits_while_its_person_turn_has_no_answer() -> None:
    assert ids(under_answers(turns("p"), [run(1, 1)])) == {}
    assert ids(under_answers(turns("ph"), [run(1, 1)])) == {}


def test_a_run_waits_for_the_answer_only_for_the_turn_still_unanswered() -> None:
    assert ids(under_answers(turns("paph"), [run(1, 1), run(2, 3)])) == {2: [1]}


def test_a_run_of_a_turn_not_among_the_turns_is_under_none() -> None:
    assert ids(under_answers(turns("pa"), [run(1, 99), run(2, 1)])) == {2: [2]}


def test_a_run_with_no_turn_is_under_none() -> None:
    bench = BenchRun(1, 1, 1, 1)
    assert ids(under_answers(turns("pa"), [run(1, None, conversation_id=None, bench=bench)])) == {}


def test_no_runs_put_none_anywhere() -> None:
    assert ids(under_answers(turns("papha"), [])) == {} and ids(under_answers([], [run(1, 1)])) == {}


def test_a_run_is_served_wired() -> None:
    got = under_answers(turns("pa"), [run(1, 1, output=None)])[2]
    assert got == [wire(run(1, 1, output=None))]


def test_a_run_sits_under_the_last_of_several_answers_not_the_first() -> None:
    assert ids(under_answers(turns("paap"), [run(1, 1)])) == {3: [1]}


def test_runs_are_ordered_oldest_first_by_id_whatever_order_they_arrive_in() -> None:
    assert ids(under_answers(turns("pa"), [run(9, 1), run(4, 1), run(5, 1)])) == {2: [4, 5, 9]}
