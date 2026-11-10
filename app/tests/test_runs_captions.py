"""Captions become stamped lines: SubRip and WebVTT cues keep their start time and words, markup and line breaks are
dropped, and a text that holds no cue gives nothing."""

from ashley.runs import captions
from ashley.runs.captions import Segment

SRT = """1
00:00:01,500 --> 00:00:03,000
Hello there.

2
00:01:05,000 --> 00:01:08,250
<i>Second</i> line
spans two rows.

3
01:02:03,004 --> 01:02:04,000
After an hour.
"""

VTT = """WEBVTT

NOTE a comment block
00:00:02.000 --> 00:00:04.000 align:start
First cue

intro
01:05.500 --> 01:07.000
Hours left out
"""


def test_subrip_cues_keep_their_start_and_their_words() -> None:
    assert captions.parse_captions(SRT) == [Segment(1.5, "Hello there."), Segment(65.0, "Second line spans two rows."),
                                            Segment(3723.004, "After an hour.")]


def test_webvtt_cues_with_settings_ids_and_short_times_are_read_and_notes_are_not() -> None:
    assert captions.parse_captions(VTT) == [Segment(2.0, "First cue"), Segment(65.5, "Hours left out")]


def test_windows_line_endings_and_a_byte_order_mark_change_nothing() -> None:
    assert captions.parse_captions("﻿" + SRT.replace("\n", "\r\n")) == captions.parse_captions(SRT)


def test_text_with_no_cue_gives_none() -> None:
    assert captions.parse_captions("just some words\n\nand more") == []
    assert captions.parse_captions("") == []


def test_a_cue_with_no_words_is_left_out() -> None:
    assert captions.parse_captions("1\n00:00:01,000 --> 00:00:02,000\n\n") == []


def test_a_stamp_is_minutes_and_seconds_and_hours_from_an_hour() -> None:
    assert [captions.stamp(s) for s in (0, 5.9, 65, 3599, 3600, 3723, -4)] == [
        "[0:00]", "[0:05]", "[1:05]", "[59:59]", "[1:00:00]", "[1:02:03]", "[0:00]"]


def test_lines_are_stamped_one_to_a_segment_and_empty_ones_are_skipped() -> None:
    lines = captions.lines_of([Segment(1, "a  b"), Segment(2, "  "), Segment(70, "c\nd")])
    assert lines == "[0:01] a b\n[1:10] c d"
