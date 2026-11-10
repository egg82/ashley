import pytest
from ashley.channels.push.later import cut
from ashley.channels.push.plain import plain_text


def test_emphasis_marks_go_and_nested_emphasis_keeps_its_words() -> None:
    assert plain_text("It's **really *very* good**, and ***bold italic***, __also__ _this_.") == (
        "It's really very good, and bold italic, also this.")


def test_a_link_is_its_label_and_an_image_its_alt_text() -> None:
    assert plain_text("Book it on [the clinic's site](https://example.org/a_b?x=1&y=(2)) now.") == (
        "Book it on the clinic's site now.")
    assert plain_text("![a map](https://example.org/m.png)") == "a map"


def test_list_items_stay_as_lines() -> None:
    got = plain_text("You need:\n- **eggs**\n* flour\n  - a [pinch](http://x.y) of salt\n1. then mix")
    assert got == "You need:\n• eggs\n• flour\n  • a pinch of salt\n1. then mix"


def test_code_spans_fences_headings_and_quotes_lose_their_marks_but_not_their_words() -> None:
    got = plain_text("## Steps\n> note\nRun `ls *.txt` first:\n```sh\nls **/*.md\n```")
    assert got == "Steps\nnote\nRun ls *.txt first:\nls **/*.md"


@pytest.mark.parametrize("text", [
    "Dinner is at 6, see you there.",
    "Use snake_case_names and 2 * 3 = 6.",
    "Line one.\n\nLine two after a blank line.",
    "",
])
def test_text_with_no_markdown_is_unchanged(text: str) -> None:
    assert plain_text(text) == text


def test_the_cut_counts_the_rendered_text() -> None:
    body = "**" + "word " * 20 + "end**"
    shown = cut(plain_text(body), 40)
    assert "*" not in shown and len(shown) <= 40 and shown.endswith("…")
