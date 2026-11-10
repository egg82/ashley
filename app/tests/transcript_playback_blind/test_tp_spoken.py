"""`captions.spoken`: the segments that have text, in the order `lines_of` writes them."""

from ashley.runs.captions import Segment, lines_of, spoken, stamp
from hypothesis import given
from hypothesis import strategies as st

TEXTS = st.sampled_from(["", " ", "  \t", "\n", "hello", " padded ", "two\nlines", "x"])
SEGMENTS = st.lists(st.builds(Segment, st.floats(min_value=0, max_value=1e5, allow_nan=False, allow_infinity=False), TEXTS),
                    max_size=10)


def test_segments_without_text_are_left_out_and_the_rest_keep_their_order() -> None:
    a, b, c, d = Segment(0, "one"), Segment(1, ""), Segment(2, "two"), Segment(3, "  ")
    assert spoken([a, b, c, d]) == [a, c]


def test_nothing_spoken_is_an_empty_list() -> None:
    assert spoken([]) == [] and spoken([Segment(0, ""), Segment(1, "   ")]) == []


def test_all_spoken_segments_come_back_unchanged() -> None:
    segs = [Segment(5, "b"), Segment(1, "a")]
    assert spoken(segs) == segs


def test_it_does_not_reorder_by_time() -> None:
    segs = [Segment(9, "late"), Segment(2, "early")]
    assert spoken(segs) == segs


@given(SEGMENTS)
def test_one_line_of_lines_of_per_spoken_segment_in_order(segments: list[Segment]) -> None:
    kept = spoken(segments)
    written = lines_of(segments)
    lines = written.split("\n") if written else []
    assert len(lines) == len(kept)
    for line, seg in zip(lines, kept, strict=True):
        assert line.startswith(stamp(seg.start))


@given(SEGMENTS)
def test_what_is_kept_is_a_subsequence_of_the_input_and_all_of_it_has_text(segments: list[Segment]) -> None:
    kept = spoken(segments)
    it = iter(segments)
    assert all(any(k is s or k == s for s in it) for k in kept)
    assert all(seg.text.strip() for seg in kept)
    assert len(kept) == sum(1 for s in segments if s.text.strip())
