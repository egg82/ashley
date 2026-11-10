"""Timestamped text and captions parsing (`ashley.runs.captions`): `stamp` rounds down to `[m:ss]` and goes to
`[h:mm:ss]` from an hour; `lines_of` is one stamped line per segment with text; `parse_captions` reads SubRip and WebVTT
cues in file order, tags dropped, lines joined by a space, and gives [] for text that holds no cue."""

import pytest
from ashley.runs.captions import Segment, lines_of, parse_captions, stamp


@pytest.mark.parametrize(("seconds", "text"), [
    (0, "[0:00]"), (0.4, "[0:00]"), (1, "[0:01]"), (9.99, "[0:09]"), (59.999, "[0:59]"), (60, "[1:00]"), (61, "[1:01]"),
    (600, "[10:00]"), (3599, "[59:59]"), (3599.999, "[59:59]"), (3600, "[1:00:00]"), (3661, "[1:01:01]"),
    (3600.9, "[1:00:00]"), (7325, "[2:02:05]"), (36000, "[10:00:00]")])
def test_a_time_is_stamped_rounded_down(seconds: float, text: str) -> None:
    assert stamp(seconds) == text


def test_one_stamped_line_per_segment() -> None:
    got = lines_of([Segment(0, "hello"), Segment(75.9, "second"), Segment(3700, "late")])
    assert got.splitlines() == ["[0:00] hello", "[1:15] second", "[1:01:40] late"]


def test_no_segments_is_no_text() -> None:
    assert lines_of([]).strip() == ""


def test_a_segment_with_no_text_is_left_out() -> None:
    got = lines_of([Segment(1, "one"), Segment(2, ""), Segment(3, "three")])
    assert got.splitlines() == ["[0:01] one", "[0:03] three"]


def test_a_line_break_inside_a_text_becomes_a_space() -> None:
    got = lines_of([Segment(1, "first\nsecond"), Segment(5, "next")])
    assert got.splitlines() == ["[0:01] first second", "[0:05] next"]


def test_segments_keep_the_order_they_are_given() -> None:
    got = lines_of([Segment(90, "late"), Segment(5, "early")])
    assert got.splitlines() == ["[1:30] late", "[0:05] early"]


SRT = "1\n00:00:01,000 --> 00:00:03,000\nhello there\n\n2\n00:01:05,500 --> 00:01:07,000\nsecond cue\n"


def test_subrip_cues_give_their_start_and_words() -> None:
    assert parse_captions(SRT) == [Segment(1.0, "hello there"), Segment(65.5, "second cue")]


def test_subrip_with_windows_line_endings() -> None:
    assert parse_captions(SRT.replace("\n", "\r\n")) == [Segment(1.0, "hello there"), Segment(65.5, "second cue")]


def test_subrip_hours_and_milliseconds() -> None:
    got = parse_captions("1\n01:02:03,004 --> 01:02:05,000\nlate\n")
    assert len(got) == 1 and got[0].text == "late" and got[0].start == pytest.approx(3723.004)


def test_the_lines_of_a_cue_are_joined_by_a_space() -> None:
    got = parse_captions("1\n00:00:01,000 --> 00:00:03,000\nfirst line\nsecond line\n")
    assert got == [Segment(1.0, "first line second line")]


def test_a_cue_number_is_not_part_of_the_cue_before_it() -> None:
    got = parse_captions(SRT)
    assert "2" not in got[0].text.split() and got[0].text == "hello there"


def test_cues_stay_in_file_order_not_time_order() -> None:
    text = "1\n00:00:30,000 --> 00:00:31,000\nlater\n\n2\n00:00:05,000 --> 00:00:06,000\nearlier\n"
    assert [s.text for s in parse_captions(text)] == ["later", "earlier"]


VTT = "WEBVTT\n\n00:01.000 --> 00:03.000\nhello there\n\n01:05.500 --> 01:07.000\nsecond cue\n"


def test_webvtt_cues_without_hours() -> None:
    assert parse_captions(VTT) == [Segment(1.0, "hello there"), Segment(65.5, "second cue")]


def test_webvtt_cues_with_hours() -> None:
    got = parse_captions("WEBVTT\n\n01:02:03.500 --> 01:02:05.000\nlate\n")
    assert got == [Segment(3723.5, "late")]


def test_the_webvtt_header_is_not_a_cue() -> None:
    got = parse_captions("WEBVTT - a title\nKind: captions\nLanguage: en\n\n00:01.000 --> 00:02.000\nonly\n")
    assert got == [Segment(1.0, "only")]


def test_a_webvtt_cue_identifier_and_settings_are_not_words() -> None:
    got = parse_captions("WEBVTT\n\nintro\n00:01.000 --> 00:02.000 align:start position:10%\nwords\n")
    assert got == [Segment(1.0, "words")]


def test_a_webvtt_note_is_not_a_cue() -> None:
    got = parse_captions("WEBVTT\n\nNOTE this is a comment\n\n00:01.000 --> 00:02.000\nspoken\n")
    assert got == [Segment(1.0, "spoken")]


@pytest.mark.parametrize(("raw", "words"), [
    ("<i>hello</i> there", "hello there"),
    ("<c.yellow>hello</c>", "hello"),
    ("<v Bob>hello Bob", "hello Bob"),
    ("he<00:00:01.500>llo", "hello"),
    ("<b><i>both</i></b>", "both"),
])
def test_markup_tags_are_dropped(raw: str, words: str) -> None:
    assert parse_captions(f"WEBVTT\n\n00:01.000 --> 00:02.000\n{raw}\n") == [Segment(1.0, words)]


def test_subrip_markup_is_dropped_too() -> None:
    assert parse_captions("1\n00:00:01,000 --> 00:00:02,000\n<font color=\"red\">red</font> text\n") == [Segment(1.0, "red text")]


@pytest.mark.parametrize("text", ["", "   \n\n", "just some words\nno times here\n", "WEBVTT\n\n", "1\nnot a time --> either\nx\n"])
def test_text_with_no_cue_gives_nothing(text: str) -> None:
    assert parse_captions(text) == []


def test_parsed_cues_make_stamped_lines() -> None:
    assert lines_of(parse_captions(SRT)).splitlines() == ["[0:01] hello there", "[1:05] second cue"]
