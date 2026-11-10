"""`Recording` and the reader body: a transcript's body names its recording and each line's start; `page_of` serves it
only when the lines number the starts; a malformed or absent one is None and the body still validates."""

import json

import pytest
from ashley.workshop.reader import Recording, body_of, page_of, well_formed
from hypothesis import given
from hypothesis import strategies as st
from transcript_playback_blind_support import raw_body

LINES = st.lists(st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp"), blacklist_characters="\n\r\x85"),
                         min_size=1, max_size=12), min_size=1, max_size=8)
TIMES = st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False)


def test_a_recording_is_a_frozen_value_of_the_piece_and_its_starts() -> None:
    r = Recording(3, (0.0, 1.5))
    assert (r.piece_id, r.starts) == (3, (0.0, 1.5))
    assert r == Recording(3, (0.0, 1.5)) and r != Recording(4, (0.0, 1.5)) and r != Recording(3, (0.0, 2.0))
    with pytest.raises(AttributeError):
        setattr(r, "piece_id", 9)


def test_a_transcript_body_reads_back_its_recording_and_its_text() -> None:
    rec = Recording(7, (0.0, 4.5, 65.0))
    page = page_of(body_of("", "Talk", "[0:00] a\n[0:04] b\n[1:05] c", rec))
    assert page is not None
    assert (page.url, page.title, page.text, page.recording) == ("", "Talk", "[0:00] a\n[0:04] b\n[1:05] c", rec)


def test_a_page_has_no_recording_by_default() -> None:
    page = page_of(body_of("https://example.com/p", "T", "one\ntwo"))
    assert page is not None and page.recording is None
    assert page.url == "https://example.com/p"


def test_the_body_is_one_json_object_of_the_documented_fields() -> None:
    body: dict[str, object] = json.loads(body_of("", "T", "a\nb", Recording(2, (0.0, 1.0))))
    assert {"url", "title", "text", "recording"} <= set(body)
    assert (body["url"], body["title"], body["text"]) == ("", "T", "a\nb")


def test_a_transcript_body_is_well_formed() -> None:
    assert well_formed(body_of("", "T", "a\nb", Recording(2, (0.0, 1.0))))


@pytest.mark.parametrize("starts", [(0.0,), (0.0, 1.0, 2.0), ()])
def test_starts_that_do_not_number_the_lines_serve_no_recording_and_the_body_still_validates(starts: tuple[float, ...]) -> None:
    body = body_of("", "T", "a\nb", Recording(2, starts))
    assert well_formed(body)
    page = page_of(body)
    assert page is not None and page.recording is None
    assert page.text == "a\nb" and page.title == "T"


def test_an_edit_that_adds_or_removes_a_line_drops_the_recording_without_touching_the_text() -> None:
    whole = json.loads(body_of("", "T", "a\nb", Recording(2, (0.0, 1.0))))
    whole["text"] = "a\nb\nc"
    page = page_of(json.dumps(whole))
    assert page is not None and page.recording is None and page.text == "a\nb\nc"
    whole["text"] = "a"
    page = page_of(json.dumps(whole))
    assert page is not None and page.recording is None


@pytest.mark.parametrize("recording", [None, "x", 5, [], [1, 2], {}, {"piece_id": 1}, {"starts": [0, 1]}, {"piece_id": "1", "starts": [0, 1]},
                                       {"piece_id": 1, "starts": "01"}, {"piece_id": 1, "starts": [0, "1"]},
                                       {"piece_id": 1, "starts": [0, None]}, {"piece_id": 1, "starts": {"a": 1}}])
def test_a_malformed_or_absent_recording_is_none_and_the_body_validates(recording: object) -> None:
    body = raw_body(recording)
    assert well_formed(body)
    page = page_of(body)
    assert page is not None and page.recording is None and page.text == "a\nb"


def test_a_hand_written_recording_of_the_right_shape_is_served() -> None:
    page = page_of(raw_body({"piece_id": 4, "starts": [0, 2.5]}))
    assert page is not None and page.recording == Recording(4, (0.0, 2.5))


def test_a_body_with_no_recording_key_at_all_is_a_page() -> None:
    page = page_of(json.dumps({"url": "", "title": "", "text": "a\nb"}))
    assert page is not None and page.recording is None


def test_an_empty_body_is_a_draft_and_has_no_page() -> None:
    assert well_formed("") and page_of("") is None


def test_a_body_that_is_not_json_is_not_a_page() -> None:
    assert page_of("not json") is None and not well_formed("not json")


@given(LINES, st.data())
def test_a_page_round_trips_through_its_body_when_starts_number_the_lines(lines: list[str], data: st.DataObject) -> None:
    starts = tuple(data.draw(st.lists(TIMES, min_size=len(lines), max_size=len(lines))))
    rec = Recording(data.draw(st.integers(min_value=1, max_value=10**9)), starts)
    text = "\n".join(lines)
    page = page_of(body_of("", "title", text, rec))
    assert page is not None
    assert (page.text, page.title, page.url, page.recording) == (text, "title", "", rec)


@given(LINES, st.lists(TIMES, max_size=12))
def test_page_of_serves_a_recording_exactly_when_the_count_matches(lines: list[str], starts: list[float]) -> None:
    page = page_of(body_of("", "t", "\n".join(lines), Recording(1, tuple(starts))))
    assert page is not None
    assert (page.recording is not None) == (len(starts) == len(lines))


def test_lines_are_separated_by_newline_only_so_other_separators_inside_a_line_do_not_split_it() -> None:
    text = "a\rb\x0bc\x0c\x85d e\nsecond"
    page = page_of(body_of("", "T", text, Recording(1, (0.0, 1.0))))
    assert page is not None and page.recording == Recording(1, (0.0, 1.0))
    page = page_of(body_of("", "T", text, Recording(1, (0.0, 1.0, 2.0))))
    assert page is not None and page.recording is None
