"""`chunks`: text split for Discord's 2000-character limit at the last paragraph break within the limit, else the last line
break, else the last space, else at the limit; pieces stripped, none empty, at most `most`, the last ending `…` (still
within the limit) when the text did not fit; blank text gives nothing; a bad limit or count is a ValueError."""

import pytest
from ashley.channels.discord.chunks import chunks
from hypothesis import given
from hypothesis import strategies as st


def compact(text: str) -> str:
    return "".join(text.split())


@pytest.mark.parametrize("text", ["", " ", "\n\n", " \t\n \n\n  "])
def test_blank_text_gives_nothing(text: str) -> None:
    assert chunks(text) == []


@pytest.mark.parametrize(("limit", "most"), [(1, 4), (0, 4), (-5, 4), (2000, 0), (2000, -1)])
def test_a_limit_under_two_or_no_pieces_is_a_value_error(limit: int, most: int) -> None:
    with pytest.raises(ValueError):
        chunks("some text", limit, most)


def test_the_smallest_allowed_limit_and_count_work() -> None:
    assert chunks("ab", 2, 1) == ["ab"]


def test_text_of_exactly_the_limit_is_one_piece_and_one_more_is_two() -> None:
    assert chunks("a" * 2000) == ["a" * 2000]
    assert chunks("a" * 2001) == ["a" * 2000, "a"]


def test_the_stripped_text_is_what_has_to_fit() -> None:
    assert chunks("  \n" + "a" * 2000 + "\n  ") == ["a" * 2000]


def test_short_text_is_returned_stripped_and_unchanged_inside() -> None:
    assert chunks("  hello\n\nthere  friend \n") == ["hello\n\nthere  friend"]


def test_a_paragraph_break_beats_a_later_line_break_and_space() -> None:
    assert chunks("aaaaaaaa\n\nbbbbbbbb\ncccc dddd", 20) == ["aaaaaaaa", "bbbbbbbb\ncccc dddd"]


def test_it_cuts_at_the_last_paragraph_break_that_fits_not_the_first() -> None:
    assert chunks("aaaa\n\nbbbb\n\ncccc", 12) == ["aaaa\n\nbbbb", "cccc"]


def test_a_line_break_beats_a_later_space() -> None:
    assert chunks("aaaaaaaa bbbb\ncccc dddd eeee", 20) == ["aaaaaaaa bbbb", "cccc dddd eeee"]


def test_a_space_is_used_when_there_is_no_line_break() -> None:
    assert chunks("aaaa bbbb cccc dddd eeee", 20) == ["aaaa bbbb cccc dddd", "eeee"]


def test_a_word_longer_than_the_limit_is_cut_hard_at_the_limit() -> None:
    assert chunks("a" * 25, 10, 5) == ["a" * 10, "a" * 10, "a" * 5]
    assert chunks("xx " + "y" * 25, 10, 5) == ["xx", "y" * 10, "y" * 10, "y" * 5]


def test_whitespace_around_a_cut_is_not_carried_into_either_piece() -> None:
    assert chunks("aaaa   \n\n   bbbb", 8) == ["aaaa", "bbbb"]


def test_pieces_are_never_blank_even_when_the_break_is_a_run_of_whitespace() -> None:
    pieces = chunks("a" + " " * 30 + "b", 10, 10)
    assert pieces == ["a", "b"]


def test_text_that_needs_exactly_the_most_pieces_is_not_marked_cut() -> None:
    assert chunks("a" * 20 + "\n\n" + "b" * 20, 25, 2) == ["a" * 20, "b" * 20]
    assert chunks("a" * 40, 20, 2) == ["a" * 20, "a" * 20]


def test_more_text_than_most_pieces_ends_the_last_with_an_ellipsis_within_the_limit() -> None:
    paragraphs = "\n\n".join(c * 15 for c in "ABCDE")
    pieces = chunks(paragraphs, 20, 2)
    assert len(pieces) == 2
    assert pieces[0] == "A" * 15
    assert pieces[1].startswith("B" * 15) and pieces[1].endswith("…")   # contract: is the last piece cut at a break first?
    assert all(len(p) <= 20 for p in pieces)
    assert "D" not in "".join(pieces) and "E" not in "".join(pieces)


def test_the_ellipsis_fits_when_the_last_piece_is_already_full() -> None:
    pieces = chunks("a" * 50, 10, 2)
    assert len(pieces) == 2 and pieces[0] == "a" * 10
    assert len(pieces[1]) <= 10 and pieces[1].endswith("…") and set(pieces[1][:-1]) == {"a"}


def test_the_smallest_limit_with_one_piece_still_ends_in_an_ellipsis() -> None:
    [only] = chunks("aaaa", 2, 1)
    assert len(only) <= 2 and only.endswith("…")


def test_text_that_fits_is_never_given_an_ellipsis() -> None:
    assert "…" not in "".join(chunks("a b c\n\nd e f\n" * 3, 2000, 4))


texts = st.lists(st.sampled_from(["a", "b", "c", "word", " ", "  ", "\n", "\n\n", "\t", "…"]), max_size=60).map("".join)
unicode_texts = st.text(max_size=120)


@given(text=st.one_of(texts, unicode_texts), limit=st.integers(2, 40), most=st.integers(1, 8))
def test_every_piece_is_within_the_limit_stripped_and_not_blank_and_there_are_at_most_most(
        text: str, limit: int, most: int) -> None:
    pieces = chunks(text, limit, most)
    assert len(pieces) <= most
    for piece in pieces:
        assert 0 < len(piece) <= limit
        assert piece == piece.strip() and piece.strip() != ""
    assert bool(pieces) == (text.strip() != "")


@given(text=st.one_of(texts, unicode_texts), limit=st.integers(2, 40))
def test_with_room_enough_the_pieces_hold_all_the_text_and_nothing_else(text: str, limit: int) -> None:
    pieces = chunks(text, limit, 10_000)
    assert compact("".join(pieces)) == compact(text)


@given(text=st.one_of(texts, unicode_texts), limit=st.integers(2, 40), most=st.integers(1, 6))
def test_a_cut_text_ends_in_an_ellipsis_and_keeps_only_the_front_of_the_text(text: str, limit: int, most: int) -> None:
    pieces = chunks(text, limit, most)
    if not pieces:
        return
    whole = compact(text)
    held = compact("".join(pieces))
    if held == whole:
        return
    assert pieces[-1].endswith("…")
    assert whole.startswith(compact("".join(pieces[:-1]) + pieces[-1][:-1]))


@given(text=st.lists(st.sampled_from(["a", "b", " ", "\n", "\n\n"]), max_size=100).map("".join), limit=st.integers(2, 30))
def test_each_piece_is_the_next_stretch_of_the_stripped_text(text: str, limit: int) -> None:
    stripped = text.strip()
    pieces = chunks(text, limit, 10_000)
    rest = stripped
    for piece in pieces:
        assert rest.startswith(piece), "each piece is the next stretch of the stripped text, cut at a break or the limit"
        rest = rest[len(piece):].lstrip()
    assert rest == ""
