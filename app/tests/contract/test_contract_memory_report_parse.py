"""`ashley.memory.report.parse`: one logfmt line, as `ashley.logs` writes it, to its fields; None for anything else;
never raises. Lines are made by the app's own formatter. Written blind from the contract."""

import pytest
from ashley.memory.report import parse
from hypothesis import given
from hypothesis import strategies as st

from report_support import T0, line


def test_bare_fields_come_back_as_strings() -> None:
    fields = parse(line("respond.done", conversation=42, kind="chat", ms=4, ok=True, ratio=0.5))
    assert fields is not None
    assert fields["event"] == "respond.done"
    assert fields["conversation"] == "42" and fields["kind"] == "chat" and fields["ms"] == "4"
    assert fields["ok"] == "true" and fields["ratio"] == "0.5"
    assert fields["level"] == "info" and fields["logger"] == "ashley.test"
    assert fields["ts"].startswith("2026-10-20T09:00:00") and fields["ts"].endswith("Z")


@pytest.mark.parametrize("value", [
    "two words", "a=b", 'say "hi"', "back\\slash", "line one\nline two", "", "all of \"it\" = \\ \n at once",
    'ends with a backslash\\', "tab\tand space",
])
def test_a_quoted_value_round_trips_through_the_apps_own_formatter(value: str) -> None:
    fields = parse(line("x.y", before="first", text=value, after="last"))
    assert fields is not None
    assert fields["text"] == value
    assert fields["before"] == "first" and fields["after"] == "last"


def test_the_escapes_are_undone_once_each() -> None:
    fields = parse(r'ts=1 event=x.y a="q\"q" b="s\\s" c="n\nn" d="\\n"')
    assert fields is not None
    assert fields["a"] == 'q"q' and fields["b"] == "s\\s" and fields["c"] == "n\nn"
    assert fields["d"] == "\\n"


def test_an_id_list_stays_one_value() -> None:
    fields = parse(line("respond.done", used_facts="3,1,2"))
    assert fields is not None and fields["used_facts"] == "3,1,2"


def test_a_trailing_newline_is_not_part_of_the_last_value() -> None:
    fields = parse(line("x.y", last="end") + "\n")
    assert fields is not None and fields["last"] == "end"


@pytest.mark.parametrize("text", [
    "", "   ", "\n", "plain text, no fields", "Traceback (most recent call last):",
    '  File "/app/ashley/x.py", line 3, in handler', "ValueError", "{\"event\": \"x.y\"}",
    "ts=2026-10-20T09:00:00.000Z level=info logger=ashley.test", "level=info conversation=3", "event",
])
def test_a_line_that_is_not_logfmt_or_has_no_event_is_none(text: str) -> None:
    assert parse(text) is None


def test_the_control_line_does_parse() -> None:
    assert parse(line("x.y", T0)) is not None


@given(st.text())
def test_parse_never_raises(text: str) -> None:
    parse(text)


@given(st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40))
def test_parse_never_raises_on_noise_around_a_real_line(noise: str) -> None:
    for text in (noise + line("x.y", a="b"), line("x.y", a="b") + noise, line("x.y", a=noise), noise + "=" + noise):
        parse(text)
