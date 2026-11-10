"""`embed.site_well_formed` from the contract: an empty body, or exactly one https URL, capped at 2000 characters, with
no credentials and no whitespace inside it; whitespace around it is trimmed."""

import pytest
from ashley.workshop.embed import site_well_formed
from hypothesis import given
from hypothesis import strategies as st

GOOD = ["", "https://example.com", "https://example.com/", "https://example.com/a/b?c=d&e=f#g", "https://sub.example.co.uk:8443/x",
        "https://127.0.0.1/x", "https://example.com/a%20b"]


@pytest.mark.parametrize("body", GOOD)
def test_an_empty_body_or_one_https_url_is_well_formed(body: str) -> None:
    assert site_well_formed(body) is True


BAD = [
    "http://example.com", "javascript:alert(1)", "javascript://example.com/%0aalert(1)", "data:text/html,<b>x</b>",
    "//example.com", "/relative/path", "example.com", "www.example.com", "ftp://example.com", "file:///etc/passwd",
    "https:example.com", "https://", "https:///x", "https://user@example.com", "https://user:pw@example.com",
    "https://example.com@evil.example", "https://:@example.com", "not a url", "https",
    "https://example.com https://other.example", "https://example.com\nhttps://other.example",
    "https://exa mple.com", "https://example.com/a b", "https://example.com/\r\nX", "https://example.com/\x00",
    "https://example.com:99999/", "https://example.com:abc/", "https://example.com:-1/",
]


@pytest.mark.parametrize("body", BAD)
def test_anything_but_one_plain_https_url_is_refused(body: str) -> None:
    assert site_well_formed(body) is False


EDGE_WHITESPACE = [" https://example.com", "https://example.com ", "https://example.com\n", "\thttps://example.com",
                   "https://example.com\u00a0", "https://example.com\u2028", "\u3000https://example.com", "https://example.com/\x0b",
                   " ", "\n", "\r"]


@pytest.mark.parametrize("body", EDGE_WHITESPACE)
def test_whitespace_around_the_url_is_accepted_and_alone_is_the_empty_body(body: str) -> None:
    assert site_well_formed(body) is True


def test_the_length_cap_is_two_thousand() -> None:
    prefix = "https://example.com/"
    assert site_well_formed(prefix + "a" * (2000 - len(prefix))) is True
    assert site_well_formed(prefix + "a" * (2001 - len(prefix))) is False


def test_a_much_longer_url_is_refused() -> None:
    assert site_well_formed("https://example.com/" + "a" * 50000) is False


@given(st.text(alphabet=st.characters(whitelist_categories=("Zs", "Zl", "Zp", "Cc")), min_size=1, max_size=3),
       st.integers(min_value=0, max_value=3))
def test_whitespace_anywhere_in_a_good_url_refuses_it(space: str, at: int) -> None:
    if not any(c.isspace() for c in space):
        return
    base = "https://example.com/path"
    cut = (8, 12, 20, 12)[at]
    assert site_well_formed(base[:cut] + space + base[cut:]) is False


@given(st.text(max_size=40))
def test_a_body_not_starting_with_https_colon_slash_slash_is_refused_unless_empty(body: str) -> None:
    if body.strip() and not body.startswith("https://"):
        assert site_well_formed(body) is False
