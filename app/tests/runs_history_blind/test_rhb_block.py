"""`history_runs.block`: one run as the model reads it."""

import re

import pytest
from ashley.channels.history_runs import block
from ashley.runs.model import BenchRun, Outcome
from rhb_support import limits, out, stored


def lines(text: str) -> list[str]:
    return text.splitlines()


def test_a_run_that_ran_has_its_markers_header_script_and_streams() -> None:
    text = block(stored(1, 5, "print('hi')", out("hi\n", "warn\n")), limits())
    rows = lines(text)
    assert rows[0] == "[code run: python, ran, exit 0]"
    assert rows[-1] == "[end code run]"
    assert "script:" in rows and "stdout:" in rows and "stderr:" in rows
    assert rows.index("script:") < rows.index("stdout:") < rows.index("stderr:")
    assert rows[rows.index("stdout:") + 1] == "hi" and rows[rows.index("stderr:") + 1] == "warn"
    assert "print('hi')" in text and "hi" in text and "warn" in text


def test_a_non_zero_exit_code_is_printed() -> None:
    assert lines(block(stored(1, 5, output=out(exit_code=3)), limits()))[0] == "[code run: python, ran, exit 3]"


@pytest.mark.parametrize("outcome,pattern", [("timed_out", r"timed[ _]out"), ("out_of_memory", r"out[ _]of[ _]memory"),
                                             ("failed", r"failed"), ("unknown", r"unknown")])
def test_another_outcome_prints_the_outcome_and_no_exit_code(outcome: Outcome, pattern: str) -> None:
    header = lines(block(stored(1, 5, output=out("partial", outcome=outcome, exit_code=None)), limits()))[0]
    assert re.search(pattern, header) and "exit" not in header
    assert header.startswith("[code run: python, ") and header.endswith("]")


def test_a_run_with_no_recorded_output_says_so() -> None:
    text = block(stored(1, 5, "print(1)", None), limits())
    assert "no result was recorded" in lines(text)[0]
    assert "print(1)" in text and lines(text)[-1] == "[end code run]"
    assert "stdout:" not in text and "stderr:" not in text


def test_the_script_is_cut_from_its_end() -> None:
    text = block(stored(1, 5, "A" * 10 + "§tail", out()), limits(script=10))
    assert "A" * 10 in text and "§" not in text and "tail" not in text


def test_a_script_of_exactly_the_budget_is_whole() -> None:
    assert "A" * 9 + "§" in block(stored(1, 5, "A" * 9 + "§", out()), limits(script=10))


def test_the_script_budget_counts_characters_not_bytes() -> None:
    text = block(stored(1, 5, "é" * 10 + "§", out()), limits(script=10))
    assert "é" * 10 in text and "§" not in text


def test_a_zero_script_budget_keeps_none_of_it() -> None:
    assert "SECRETSCRIPT" not in block(stored(1, 5, "SECRETSCRIPT", out("o")), limits(script=0))


def test_each_stream_keeps_its_tail() -> None:
    text = block(stored(1, 5, "s", out("§" + "x" * 5 + "Y" * 10, "§" + "x" * 5 + "Z" * 10)), limits(output=10))
    assert "Y" * 10 in text and "Z" * 10 in text and "§" not in text
    assert "Y" * 11 not in text


def test_a_stream_of_exactly_the_budget_is_whole() -> None:
    text = block(stored(1, 5, "s", out("§" + "Y" * 9)), limits(output=10))
    assert "§" + "Y" * 9 in text


def test_the_streams_are_cut_apart_not_together() -> None:
    text = block(stored(1, 5, "s", out("O" * 3, "E" * 30)), limits(output=10))
    assert "OOO" in text and "E" * 10 in text and "E" * 11 not in text


def test_a_zero_output_budget_keeps_no_output() -> None:
    text = block(stored(1, 5, "s", out("SECRETOUT", "SECRETERR")), limits(output=0))
    assert "SECRETOUT" not in text and "SECRETERR" not in text


def test_the_names_of_files_made_come_but_never_their_contents() -> None:
    text = block(stored(1, 5, "s", out(files={"a.txt": "CONTENTSA", "b.csv": "CONTENTSB"})), limits())
    assert "files made:" in text and "a.txt" in text and "b.csv" in text
    assert "CONTENTSA" not in text and "CONTENTSB" not in text


def test_stdin_and_input_files_never_come() -> None:
    text = block(stored(1, 5, "s", out("o"), stdin="SECRETSTDIN", files={"in.txt": "SECRETFILE"}), limits())
    assert "SECRETSTDIN" not in text and "SECRETFILE" not in text and "in.txt" not in text


def test_a_run_that_made_no_files_has_no_files_line() -> None:
    assert "files made" not in block(stored(1, 5, "s", out("o")), limits())


def test_the_block_is_the_same_for_a_run_made_with_a_bench() -> None:
    plain = stored(1, 5, "s", out("o"))
    benched = stored(1, 5, "s", out("o"), bench=BenchRun(1, 1, 1, 1))
    assert block(plain, limits()) == block(benched, limits())


def test_a_script_and_streams_within_their_budgets_are_not_marked_as_cut() -> None:
    run = stored(1, 5, "S" * 10, out("O" * 10, "E" * 10))
    assert block(run, limits(script=10, output=10)) == block(run, limits(script=1000, output=1000))
