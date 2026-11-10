"""Reading the runner's last marked line: checked and cut again, since the script can print that line too."""

import json
from typing import Any

import pytest
from ashley.runs.envelope import parse
from ashley.runs.runner import MARK
from hypothesis import given, settings
from hypothesis import strategies as st
from sandbox_support import CONFIG, envelope_line


def raw(**over: Any) -> str:
    body: dict[str, Any] = {"exit_code": 0, "timed_out": False, "stdout": "", "stderr": "", "cut": False,
                            "files": {}, "skipped": []}
    return MARK + json.dumps({**body, **over})


def test_the_last_marked_line_is_the_result() -> None:
    log = "noise\n" + raw(stdout="first") + "\nmore noise\n" + raw(stdout="last") + "\n"
    output = parse(log, CONFIG)
    assert output is not None and output.stdout == "last"


def test_a_ran_output_carries_its_exit_code_and_a_timeout_carries_none() -> None:
    ran = parse(envelope_line(7), CONFIG)
    timed = parse(envelope_line(None, timed_out=True), CONFIG)
    assert ran is not None and (ran.outcome, ran.exit_code) == ("ran", 7)
    assert timed is not None and (timed.outcome, timed.exit_code) == ("timed_out", None)


@pytest.mark.parametrize("log", [
    "", "plain text", MARK, MARK + "not json", MARK + "[]", MARK + "null", MARK + '"s"', MARK + "{}",
    raw(stdout=5), raw(stderr=None), raw(exit_code="0"), raw(timed_out="no"),
])
def test_a_missing_or_malformed_line_is_none(log: str) -> None:
    assert parse(log, CONFIG) is None


@pytest.mark.parametrize("log", [raw(files=[]), raw(files={"a": 1}), raw(skipped="a"), raw(skipped=[1])])
def test_malformed_file_fields_are_dropped_or_the_line_refused_never_passed_on(log: str) -> None:
    output = parse(log, CONFIG)
    assert output is None or (output.files == {} and output.skipped == ())


def test_a_malformed_last_line_is_not_rescued_by_an_earlier_good_one() -> None:
    assert parse(raw(stdout="good") + "\n" + MARK + "{broken", CONFIG) is None


def test_each_stream_is_cut_to_the_limit_and_says_so() -> None:
    output = parse(raw(stdout="a" * 1_000, stderr="b" * 1_000), CONFIG)
    assert output is not None and output.cut
    assert output.stdout == "a" * CONFIG.output_chars and output.stderr == "b" * CONFIG.output_chars


def test_the_runners_own_cut_flag_is_passed_on() -> None:
    output = parse(raw(stdout="short", cut=True), CONFIG)
    assert output is not None and output.cut and output.stdout == "short"


def test_output_within_the_limits_is_untouched_and_not_cut() -> None:
    output = parse(raw(stdout="a" * CONFIG.output_chars, stderr="é"), CONFIG)
    assert output is not None and not output.cut
    assert output.stdout == "a" * CONFIG.output_chars and output.stderr == "é"


def test_files_past_the_count_or_the_size_are_skipped_by_name() -> None:
    files = {"big": "x" * (CONFIG.file_chars + 1), "one": "1", "two": "2", "three": "3"}
    output = parse(raw(files=files), CONFIG)
    assert output is not None
    assert len(output.files) <= CONFIG.max_files
    assert "big" not in output.files and "big" in output.skipped
    assert set(output.files) | set(output.skipped) == set(files)
    assert all(len(text) <= CONFIG.file_chars for text in output.files.values())


def test_names_the_runner_already_skipped_stay_skipped() -> None:
    output = parse(raw(skipped=["blob.bin"]), CONFIG)
    assert output is not None and output.skipped == ("blob.bin",)


json_values = st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=80),
                           lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=8), inner, max_size=4),
                           max_leaves=12)
envelopes = st.fixed_dictionaries({"exit_code": st.none() | st.integers(-300, 300), "timed_out": st.booleans(),
                                   "stdout": st.text(max_size=300), "stderr": st.text(max_size=300),
                                   "cut": st.booleans(), "files": st.dictionaries(st.text(max_size=10), st.text(max_size=100), max_size=6),
                                   "skipped": st.lists(st.text(max_size=10), max_size=4)})


@given(st.text(max_size=400))
@settings(max_examples=150, deadline=None)
def test_any_text_parses_or_is_none_and_never_raises(text: str) -> None:
    parse(text, CONFIG)
    parse(MARK + text, CONFIG)


@given(json_values)
@settings(max_examples=150, deadline=None)
def test_any_json_after_the_mark_parses_or_is_none(value: Any) -> None:
    parse(MARK + json.dumps(value), CONFIG)


@given(envelopes, st.text(max_size=100))
@settings(max_examples=150, deadline=None)
def test_whatever_a_forged_line_reports_the_output_stays_inside_the_limits(body: dict[str, Any], noise: str) -> None:
    output = parse(noise.replace("\n", " ") + "\n" + MARK + json.dumps(body), CONFIG)
    if output is None:
        return
    assert len(output.stdout) <= CONFIG.output_chars and len(output.stderr) <= CONFIG.output_chars
    assert len(output.files) <= CONFIG.max_files
    assert all(len(text) <= CONFIG.file_chars for text in output.files.values())
    assert (output.exit_code is None) == (output.outcome != "ran")
    if len(body["stdout"]) > CONFIG.output_chars or len(body["stderr"]) > CONFIG.output_chars:
        assert output.cut
