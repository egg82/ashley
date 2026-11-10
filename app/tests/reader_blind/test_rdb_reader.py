"""`ashley.workshop.reader` from its contract: the body round trip, which bodies are pages, which passages a page
holds, and `locate` resolving a quote only when it occurs exactly once, inside one paragraph, counted in code points."""

import json

import pytest
from ashley.workshop.reader import Page, Passage, body_of, holds, locate, page_of, well_formed
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from reader_blind_support import TEXT, TITLE, URL


def page(text: str) -> Page:
    return Page(URL, TITLE, text)


# --- the body --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "one line", "a\nb\nc", "a\n\nb", "trailing\n", "\nleading", "quote \" and \\ and\ttab",
                                  "emoji 😀 and café", "é combining", "  odd separators \x85"])
@pytest.mark.parametrize("title", ["", "A title", "Tïtle 😀"])
def test_a_body_round_trips_to_the_page_it_was_made_from(text: str, title: str) -> None:
    assert page_of(body_of(URL, title, text)) == Page(URL, title, text)


def test_the_body_is_one_json_object_of_exactly_url_title_and_text() -> None:
    loaded = json.loads(body_of(URL, TITLE, TEXT))
    assert loaded == {"url": URL, "title": TITLE, "text": TEXT}


def test_a_body_made_by_body_of_is_well_formed() -> None:
    assert well_formed(body_of(URL, "", "")) and well_formed(body_of(URL, TITLE, TEXT))


def test_an_empty_body_is_well_formed_but_is_no_page() -> None:
    assert well_formed("") is True
    assert page_of("") is None


BAD_BODIES = {
    "not json": "just words",
    "a list": json.dumps([URL, TITLE, TEXT]),
    "a string": json.dumps(URL),
    "no url": json.dumps({"title": TITLE, "text": TEXT}),
    "no title": json.dumps({"url": URL, "text": TEXT}),
    "no text": json.dumps({"url": URL, "title": TITLE}),
    "an extra field": json.dumps({"url": URL, "title": TITLE, "text": TEXT, "extra": 1}),
    "an http url": json.dumps({"url": "http://example.org/a", "title": TITLE, "text": TEXT}),
    "a javascript url": json.dumps({"url": "javascript:alert(1)", "title": TITLE, "text": TEXT}),
    "a file url": json.dumps({"url": "file:///etc/passwd", "title": TITLE, "text": TEXT}),
    "a url with no host": json.dumps({"url": "https://", "title": TITLE, "text": TEXT}),
    "a numeric url": json.dumps({"url": 5, "title": TITLE, "text": TEXT}),
    "a numeric title": json.dumps({"url": URL, "title": 5, "text": TEXT}),
    "a null title": json.dumps({"url": URL, "title": None, "text": TEXT}),
    "a numeric text": json.dumps({"url": URL, "title": TITLE, "text": 5}),
    "a null text": json.dumps({"url": URL, "title": TITLE, "text": None}),
    "an empty object": "{}",
}


@pytest.mark.parametrize("name", sorted(BAD_BODIES))
def test_a_body_that_is_not_a_page_is_not_one_and_is_not_well_formed(name: str) -> None:
    assert page_of(BAD_BODIES[name]) is None
    assert well_formed(BAD_BODIES[name]) is False


def test_an_empty_url_is_a_page_from_no_address() -> None:
    assert page_of(body_of("", "Transcript", "[0:01] hello")) == Page("", "Transcript", "[0:01] hello")


def test_an_https_url_with_a_path_query_and_port_is_accepted() -> None:
    for url in ("https://example.org/", "https://example.org:8443/a/b?q=1#f", "https://sub.example.org/x"):
        assert page_of(body_of(url, "", "t")) == Page(url, "", "t")


# --- paragraphs ------------------------------------------------------------------------------------------------------


def test_paragraphs_are_the_lines_of_the_text() -> None:
    assert page("a\nb").paragraphs == ("a", "b")
    assert page("one").paragraphs == ("one",)
    assert page("a\n\nb").paragraphs == ("a", "", "b")
    assert page("a\n").paragraphs == ("a", "")
    assert page("").paragraphs == ("",)


# --- holds -----------------------------------------------------------------------------------------------------------


P = page("hello world\nsecond")


@pytest.mark.parametrize("passage", [Passage(0, 0, 5), Passage(0, 6, 11), Passage(0, 0, 11), Passage(0, 10, 11),
                                     Passage(1, 0, 6), Passage(1, 5, 6), Passage(0, 3, 4)])
def test_a_non_empty_range_inside_one_paragraph_is_held(passage: Passage) -> None:
    assert holds(P, passage) is True


@pytest.mark.parametrize("passage", [Passage(0, 3, 3), Passage(0, 0, 0), Passage(0, 11, 11), Passage(0, 5, 4),
                                     Passage(0, 0, 12), Passage(0, 11, 12), Passage(0, 12, 13), Passage(1, 0, 7),
                                     Passage(0, -1, 3), Passage(1, -3, -1), Passage(2, 0, 1), Passage(-1, 0, 1),
                                     Passage(5, 0, 1)])
def test_an_empty_backwards_or_overrunning_range_or_a_missing_paragraph_is_not_held(passage: Passage) -> None:
    assert holds(P, passage) is False


def test_holds_counts_code_points_not_utf16_units_or_bytes() -> None:
    p = page("a😀b")
    assert holds(p, Passage(0, 0, 3)) is True
    assert holds(p, Passage(0, 1, 2)) is True
    assert holds(p, Passage(0, 0, 4)) is False
    combining = page("é")
    assert holds(combining, Passage(0, 0, 2)) is True
    assert holds(combining, Passage(0, 0, 3)) is False


def test_holds_judges_the_paragraph_it_names() -> None:
    p = page("long long long\nshort")
    assert holds(p, Passage(0, 0, 14)) is True
    assert holds(p, Passage(1, 0, 14)) is False
    assert holds(p, Passage(1, 0, 5)) is True


# --- locate ----------------------------------------------------------------------------------------------------------


def test_locate_finds_a_quote_that_occurs_once() -> None:
    p = page(TEXT)
    assert locate(p, "first line") == Passage(0, 4, 14)
    assert locate(p, "Fourth line with some words.") == Passage(3, 0, 28)


def test_locate_gives_the_paragraph_and_offset_within_that_paragraph() -> None:
    p = page("aaa\nbbb ccc\nddd")
    assert locate(p, "ccc") == Passage(1, 4, 7)
    assert locate(p, "ddd") == Passage(2, 0, 3)
    assert locate(p, "aaa") == Passage(0, 0, 3)


def test_locate_counts_code_points_after_non_bmp_characters() -> None:
    p = page("😀😀 target 😀")
    got = locate(p, "target")
    assert got == Passage(0, 3, 9)
    assert p.paragraphs[0][3:9] == "target"


def test_locate_counts_code_points_after_combining_accents() -> None:
    p = page("café au lait")
    assert locate(p, "au") == Passage(0, 6, 8)


def test_locate_can_quote_the_emoji_and_combining_pair_itself() -> None:
    assert locate(page("x😀y"), "😀") == Passage(0, 1, 2)
    assert locate(page("aéb"), "é") == Passage(0, 1, 3)


def test_a_repeated_phrase_in_one_paragraph_is_none() -> None:
    assert locate(page("again and again"), "again") is None


def test_a_phrase_in_two_paragraphs_is_none() -> None:
    assert locate(page("shared words\nother shared words"), "shared") is None
    assert locate(page("x\ny\nx"), "x") is None


def test_a_longer_quote_that_is_unique_resolves_where_its_prefix_repeats() -> None:
    p = page("again and again, then done")
    assert locate(p, "again, then") == Passage(0, 10, 21)


def test_a_quote_across_a_paragraph_boundary_is_none() -> None:
    p = page("end of one\nstart of two")
    assert locate(p, "one\nstart") is None
    assert locate(p, "\n") is None
    assert locate(p, "end of one\nstart of two") is None


def test_a_quote_that_is_absent_or_empty_is_none() -> None:
    p = page(TEXT)
    assert locate(p, "nowhere in the text") is None
    assert locate(p, "") is None


def test_locate_is_case_and_whitespace_exact() -> None:
    p = page("Hello  World")
    assert locate(p, "hello") is None
    assert locate(p, "Hello World") is None
    assert locate(p, "Hello  World") == Passage(0, 0, 12)


def test_a_quote_equal_to_a_whole_paragraph_resolves() -> None:
    assert locate(page("only\nother"), "only") == Passage(0, 0, 4)
    assert locate(page("only"), "only") == Passage(0, 0, 4)


def test_a_paragraph_of_a_quote_that_is_a_suffix_of_another_is_still_a_second_occurrence() -> None:
    assert locate(page("abc\nxabc"), "abc") is None


def test_overlapping_occurrences_are_more_than_one() -> None:
    assert locate(page("aaa"), "aa") is None
    assert locate(page("ababa"), "aba") is None
    assert locate(page("aaaa"), "aaaa") == Passage(0, 0, 4)


def test_an_empty_quote_is_none_even_where_a_single_empty_paragraph_would_hold_it() -> None:
    assert locate(page(""), "") is None
    assert locate(page("\n"), "") is None
    assert locate(page("x"), "") is None


# --- properties ------------------------------------------------------------------------------------------------------

ALPHABET = st.sampled_from(list("abc d.é") + ["́", "😀", "\U0001f9d1", "ß"])
PARAGRAPH = st.text(ALPHABET, max_size=14)
PARAGRAPHS = st.lists(PARAGRAPH, min_size=1, max_size=5)


def overlapping(haystack: str, needle: str) -> int:
    return sum(1 for i in range(len(haystack) - len(needle) + 1) if haystack.startswith(needle, i))


@settings(max_examples=250, deadline=None)
@given(paragraphs=PARAGRAPHS, data=st.data())
def test_locate_round_trips_every_unique_substring_and_holds_what_it_returns(paragraphs: list[str], data: st.DataObject) -> None:
    p = page("\n".join(paragraphs))
    index = data.draw(st.integers(0, len(paragraphs) - 1))
    source = paragraphs[index]
    assume(source)
    start = data.draw(st.integers(0, len(source) - 1))
    end = data.draw(st.integers(start + 1, len(source)))
    quote = source[start:end]
    total = sum(overlapping(para, quote) for para in paragraphs)
    plain = sum(para.count(quote) for para in paragraphs)
    assume(total == plain)
    got = locate(p, quote)
    if total == 1:
        assert got == Passage(index, start, end)
        assert got is not None and holds(p, got)
        assert p.paragraphs[got.paragraph][got.start:got.end] == quote
    else:
        assert got is None


@settings(max_examples=200, deadline=None)
@given(paragraphs=PARAGRAPHS, data=st.data())
def test_a_quote_spanning_two_paragraphs_is_never_located(paragraphs: list[str], data: st.DataObject) -> None:
    assume(len(paragraphs) >= 2)
    i = data.draw(st.integers(0, len(paragraphs) - 2))
    left = paragraphs[i][data.draw(st.integers(0, len(paragraphs[i]))):]
    right = paragraphs[i + 1][:data.draw(st.integers(0, len(paragraphs[i + 1])))]
    assert locate(page("\n".join(paragraphs)), left + "\n" + right) is None


@settings(max_examples=200, deadline=None)
@given(paragraphs=PARAGRAPHS, data=st.data())
def test_whatever_locate_returns_is_held_and_quotes_the_text(paragraphs: list[str], data: st.DataObject) -> None:
    p = page("\n".join(paragraphs))
    quote = data.draw(st.text(ALPHABET, min_size=0, max_size=4))
    got = locate(p, quote)
    if got is not None:
        assert holds(p, got) and p.paragraphs[got.paragraph][got.start:got.end] == quote


@settings(max_examples=200, deadline=None)
@given(paragraphs=PARAGRAPHS, passage=st.builds(Passage, st.integers(-1, 6), st.integers(-2, 16), st.integers(-2, 16)))
def test_holds_is_a_non_empty_range_inside_one_paragraph(paragraphs: list[str], passage: Passage) -> None:
    p = page("\n".join(paragraphs))
    inside = (0 <= passage.paragraph < len(paragraphs) and 0 <= passage.start < passage.end
              and passage.end <= len(paragraphs[passage.paragraph]))
    assert holds(p, passage) is inside


@settings(max_examples=150, deadline=None)
@given(text=st.text(st.sampled_from(list("ab\n 😀é\"\\")), max_size=30), title=st.text(max_size=10))
def test_a_body_round_trips_for_any_text(text: str, title: str) -> None:
    assert page_of(body_of(URL, title, text)) == Page(URL, title, text)
    assert well_formed(body_of(URL, title, text))
