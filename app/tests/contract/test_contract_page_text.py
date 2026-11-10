"""`page_text.text_of`: the contents of script, style, noscript, svg, nav, header, footer, aside, form and template are
dropped (nested, unclosed, or with a stray end tag); block elements sit on their own lines and inline ones do not;
entities are unescaped once; whitespace is collapsed. The last tests run an invented page shaped like a clinic
site's (`search_page_clinic.html`)."""

from pathlib import Path

import pytest
from ashley.tools.page_text import text_of

PAGE = Path(__file__).with_name("search_page_clinic.html")
DROPPED = ["script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "template"]


def lines(html: str) -> list[str]:
    return [ln.strip() for ln in text_of(html).splitlines() if ln.strip()]


@pytest.mark.parametrize("tag", DROPPED)
def test_a_dropped_elements_contents_go_and_the_text_around_it_stays(tag: str) -> None:
    html = f"<p>keep one</p><{tag}>DROP <b>inner</b> text</{tag}><p>keep two</p>"
    assert text_of(html).split() == ["keep", "one", "keep", "two"]
    assert text_of(f"<{tag}>DROP</{tag}>").strip() == ""


def test_the_control_text_survives_without_the_dropped_element() -> None:
    assert text_of("<p>keep one</p><div>DROP inner text</div><p>keep two</p>").split() == [
        "keep", "one", "DROP", "inner", "text", "keep", "two"]


def test_a_nested_dropped_element_ends_only_at_its_own_end_tag() -> None:
    html = "<div><nav><ul><li>Home</li><nav>inner</nav>still nav</ul></nav>tail</div>"
    assert text_of(html).split() == ["tail"]


def test_dropped_elements_of_different_kinds_nest() -> None:
    assert text_of("<header><form>a</form>b</header>c <footer><aside>d</aside>e</footer>f").split() == ["c", "f"]


def test_tags_inside_a_script_are_not_markup() -> None:
    html = '<p>a</p><script>if (x<y) { document.write("<p>DROP</p></div>"); }</script><p>b</p>'
    assert text_of(html).split() == ["a", "b"]


def test_a_void_element_inside_a_dropped_one_does_not_end_it() -> None:
    assert text_of("<nav><img src=x><br><input>hidden</nav>shown").split() == ["shown"]


def test_an_unclosed_dropped_element_drops_the_rest_without_raising() -> None:
    assert text_of("<p>a</p><script>var x = 1;").split() == ["a"]
    assert text_of("<p>a</p><nav><a>b").split() == ["a"]


def test_a_stray_end_tag_does_not_swallow_or_drop_what_follows() -> None:
    assert text_of("</nav></div>text<p>unclosed").split() == ["text", "unclosed"]
    assert text_of("</footer></script><p>after</p>").split() == ["after"]


def test_svg_titles_and_text_go_with_the_svg() -> None:
    assert text_of("<p>a</p><svg><title>Icon</title><text>glyph</text></svg><p>b</p>").split() == ["a", "b"]


def test_comments_and_the_doctype_are_not_text() -> None:
    assert text_of("<!DOCTYPE html><!-- hidden --><p>shown</p>").split() == ["shown"]


@pytest.mark.parametrize("tag", ["p", "div", "h1", "h2", "li", "section", "article", "blockquote", "tr"])
def test_block_elements_are_on_their_own_lines(tag: str) -> None:
    assert lines(f"<{tag}>alpha</{tag}><{tag}>beta</{tag}>gamma") == ["alpha", "beta", "gamma"]


def test_a_list_gives_one_line_per_item() -> None:
    assert lines("<ul><li>Acid reflux</li><li>Allergies</li><li>Burns</li></ul>") == ["Acid reflux", "Allergies", "Burns"]


def test_inline_elements_stay_on_their_line() -> None:
    assert lines("<p>one <b>two</b> <a href='/x'>three</a> <span>four</span></p>") == ["one two three four"]
    assert lines("<p>pre<b>mid</b>post</p>") == ["premidpost"]


def test_whitespace_is_collapsed() -> None:
    assert lines("<p>a   \n\t  b</p>\n\n   <p>  c  </p>") == ["a b", "c"]
    out = text_of("  <p>x \t  y</p>  \r\n  <div>z</div>  ")
    assert "\t" not in out and "\r" not in out and "  " not in out and out.strip().split() == ["x", "y", "z"]


def test_entities_are_unescaped_once() -> None:
    assert lines("<p>Fish &amp; chips &lt;b&gt; &quot;q&quot; &#39;s&#39; caf&eacute; &#x2014; it&rsquo;s</p>") == [
        "Fish & chips <b> \"q\" 's' café — it’s"]
    assert lines("<p>&amp;lt; and &amp;amp;</p>") == ["&lt; and &amp;"]
    assert lines("<p>AT&T and 5 < 6</p>") == ["AT&T and 5 < 6"]


def test_empty_and_text_only_inputs() -> None:
    assert text_of("") == "" and text_of("<script>x</script>").strip() == ""
    assert text_of("just text").strip() == "just text"


def test_one_call_leaves_nothing_behind_for_the_next() -> None:
    alone = text_of("<p>second</p>")
    text_of("<nav><p>unfinished<script>")
    assert text_of("<p>second</p>") == alone


# a page shaped like a real site's

def real() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_page_has_what_these_tests_rely_on() -> None:
    html = real()
    for needle in ("Jobs at Brightwater", "Sign Up For Our Newsletter", "Copyright 1999", "Search by facility name",
                   "Bank Institution", "__NEXT_DATA__", "Urgent care centers in Springfield", "you&rsquo;ll be seen",
                   "Brightwater&reg;", "<li>Acid reflux</li>", "<li>Allergies</li>"):
        assert needle in html, needle
    assert 25_000 < len(html) < 40_000


def test_a_full_page_keeps_its_content_and_loses_its_furniture() -> None:
    out = text_of(real())
    assert "Urgent care centers in Springfield" in out and "Medical conditions we treat" in out
    assert "you’ll be seen by one of doctors" in out and "Brightwater®" in out
    for gone in ("Jobs at Brightwater", "Sign Up For Our Newsletter", "Copyright 1999", "Search by facility name",
                 "Bank Institution", "Stethoscope", "__NEXT_DATA__", "pageProps", "&rsquo;", "&reg;", "&amp;"):
        assert gone not in out, gone
    assert 2000 < len(out) < len(real()) // 4


def test_a_full_page_puts_list_items_on_their_own_lines_and_collapses_whitespace() -> None:
    out = text_of(real())
    rows = [ln.strip() for ln in out.splitlines()]
    assert "Acid reflux" in rows and "Allergies" in rows and rows.index("Allergies") > rows.index("Acid reflux")
    assert "\t" not in out and "  " not in out
