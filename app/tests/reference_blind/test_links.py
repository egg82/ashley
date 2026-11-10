"""`bench_reference.links_in`: the URLs written in prose or JSON, which is what a person's turn and a bench piece vouch
with."""

import json

import pytest
from ashley.tools.bench_reference import links_in

URL = "https://example.org/a/b?x=1"


@pytest.mark.parametrize("text", [
    URL, f"see {URL} please", f"({URL})", f"{URL}.", f"{URL},", f"<{URL}>", f'"{URL}"', f"line one\n{URL}\nline three",
    json.dumps({"url": URL, "start": 5}), json.dumps({"url": URL}), f"a\t{URL}\tb"])
def test_a_url_in_text_is_found_whole(text: str) -> None:
    assert URL in links_in(text)


@pytest.mark.parametrize("text", ["", "no links here", "example.org/a", "ftp://example.org/a", "https:/example.org"])
def test_text_without_an_http_url_has_no_links(text: str) -> None:
    assert not [u for u in links_in(text) if "example.org" in u]


def test_http_urls_and_several_urls_are_all_found() -> None:
    got = links_in("a http://one.example/x then https://two.example/y and https://three.example/z.")
    assert {"http://one.example/x", "https://two.example/y", "https://three.example/z"} <= got


def test_a_url_with_closing_punctuation_inside_it_is_kept() -> None:
    wiki = "https://en.wikipedia.org/wiki/Foo_(bar)"
    assert wiki in links_in(f"look: {wiki}")


def test_a_different_url_is_not_found_by_prefix() -> None:
    assert "https://example.org/a" not in links_in("https://example.org/a/b")


def test_links_come_back_as_a_frozenset_of_strings() -> None:
    got = links_in(URL)
    assert isinstance(got, frozenset) and all(isinstance(u, str) for u in got)


def test_a_url_that_holds_another_url_in_its_query_is_found_whole() -> None:
    outer = "https://example.org/redirect?to=http://other.example/x"
    assert outer in links_in(f"go {outer}")
