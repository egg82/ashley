"""`page_text.text_of`: a page's readable text, against an invented page and small planted ones."""

import pytest

from ashley.tools.page_text import text_of
from page_support import PAGE_HTML


def test_the_captured_page_gives_its_hours_and_none_of_its_scripts() -> None:
    text = text_of(PAGE_HTML)
    lines = text.split("\n")
    assert lines[0] == "Elm Street Walk-In Clinic | Urgent Care - Springfield, ST | Directory"
    hours = lines.index("Hours")
    assert lines[hours + 1:hours + 3] == ["Mon8:00am - 9:00pm", "Tue8:00am - 9:00pm"]
    assert "Sun8:00am - 5:00pm" in lines
    assert "function" not in text and "{" not in text and "  " not in text
    assert len(text) < len(PAGE_HTML) / 20


@pytest.mark.parametrize("tag", ["script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form",
                                 "template"])
def test_the_contents_of_chrome_and_code_are_dropped(tag: str) -> None:
    assert text_of(f"<p>before</p><{tag}><p>HIDDEN</p> HIDDEN</{tag}><p>after</p>") == "before\nafter"


def test_a_dropped_element_nested_in_another_stays_dropped_until_the_outer_closes() -> None:
    assert text_of("<nav>a<nav>b</nav>HIDDEN</nav>shown") == "shown"


def test_blocks_go_on_their_own_lines_and_inline_text_runs_on() -> None:
    page = "<h1>Title</h1><div>one <b>bold</b> <a href='x'>link</a></div><ul><li>a</li><li>b</li></ul>x<br>y"
    assert text_of(page) == "Title\none bold link\na\nb\nx\ny"


def test_whitespace_collapses_and_blank_lines_go() -> None:
    assert text_of("<p>  a \t\n  b  </p>\n\n\n<p>\n</p><p>c</p>") == "a b\nc"


def test_entities_are_unescaped() -> None:
    assert text_of("<p>Fish &amp; chips &lt;3 &#8211; caf&eacute;&nbsp;open</p>") == "Fish & chips <3 – café open"


def test_plain_text_and_nothing_pass_through() -> None:
    assert text_of("just words") == "just words"
    assert text_of("") == ""


def test_the_title_is_the_first_title_with_its_whitespace_collapsed_and_never_an_svgs() -> None:
    from ashley.tools.page_text import title_of
    assert title_of("<head><title>\n A  b\tc </title></head><p>x</p>") == "A b c"
    assert title_of("<svg><title>icon</title></svg><title>Real</title><title>Second</title>") == "Real"
    assert title_of("<p>no title</p>") == ""
    assert text_of("<title>T</title><p>x</p>") == "T\nx"
